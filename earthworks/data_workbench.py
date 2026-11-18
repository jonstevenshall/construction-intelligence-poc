"""Human-operated structured ingestion and an inventory of the actual data model."""
import csv
import hashlib
import io
import json
import re
from datetime import date
from pathlib import Path
from threading import RLock

from .datasets import DatasetCatalog,identifier

MAX_UPLOAD_BYTES=2_000_000
MAX_IMPORT_ROWS=1000
IMPORT_LOCK=RLock()
MODEL_TABLES=[
 ('projects','Projects','Project entity','Locate and describe the work used to interpret quotations.'),
 ('vendors','Suppliers','Supplier entity','Identify the supplier and its depot.'),
 ('quotes','Quotations','Commercial offer','Retain submitted prices, dates, terms and supplier/project identity.'),
 ('quote_lines','Quotation lines','Priced scope item','Compare quantities, units, rates and inclusion status.'),
 ('chunks','Bid text index','Retrieval projection','Find original quotation evidence; lexical vectors are not financial truth.'),
 ('context_edges','Commercial relationships','Graph edges','Connect projects, suppliers, offers, scope and original documents.'),
 ('weather_days','Rainfall observations','Public time series','Provide regional historical rainfall evidence.'),
 ('diesel_prices','Diesel observations','Public time series','Provide dated Brisbane wholesale fuel context.'),
 ('soil_screenings','Regional soil screenings','Public spatial screening','Provide mapped regional soil context with location limitations.'),
 ('public_context_edges','Public context relationships','Graph edges','Connect synthetic procurement records to regional public evidence.')]


def canonical(value):
    return json.dumps(value,ensure_ascii=False,sort_keys=True,allow_nan=False,separators=(',',':')).encode()


def day(value):
    if not isinstance(value,str):raise ValueError('Dates must use YYYY-MM-DD')
    parsed=date.fromisoformat(value)
    if parsed.isoformat()!=value:raise ValueError('Dates must use YYYY-MM-DD')
    return value


def parse_upload(filename,content):
    if not isinstance(filename,str) or not 1<=len(filename)<=200 or not isinstance(content,str):
        raise ValueError('Choose a CSV, JSON or JSONL file')
    if not 0<len(content.encode())<=MAX_UPLOAD_BYTES:raise ValueError('Upload at most 2 MB')
    suffix=Path(filename).suffix.lower()
    parsed_content=content.lstrip('\ufeff')
    try:
        if suffix=='.csv':
            reader=csv.DictReader(io.StringIO(parsed_content))
            if not reader.fieldnames or len(set(reader.fieldnames))!=len(reader.fieldnames) or any(not f for f in reader.fieldnames):
                raise ValueError('CSV needs unique, non-empty column headers')
            rows=[]
            for row in reader:
                if None in row:raise ValueError('CSV row has more values than headers')
                rows.append(row)
                if len(rows)>MAX_IMPORT_ROWS:break
        elif suffix=='.json':
            parsed=json.loads(parsed_content)
            rows=parsed.get('records') if isinstance(parsed,dict) else parsed
        elif suffix in ['.jsonl','.ndjson']:
            rows=[]
            for line in parsed_content.splitlines():
                if line.strip():rows.append(json.loads(line))
                if len(rows)>MAX_IMPORT_ROWS:break
        else:raise ValueError('Supported files: CSV, JSON, JSONL')
    except (csv.Error,json.JSONDecodeError) as exc:
        raise ValueError('Could not parse this structured file: '+str(exc)[:200]) from None
    if not isinstance(rows,list) or not 1<=len(rows)<=MAX_IMPORT_ROWS:
        raise ValueError('Import between 1 and 1,000 records per batch')
    if any(not isinstance(row,dict) or not row for row in rows):raise ValueError('Each record must be a non-empty object')
    fields=sorted({key for row in rows for key in row})
    if len(fields)>80 or any(not isinstance(key,str) or len(key)>120 for key in fields):raise ValueError('Use at most 80 short field names')
    canonical(rows) # Reject NaN, infinity and unsupported values before touching storage.
    return rows,fields


class DataWorkbench:
    def __init__(self,store):
        self.store=store

    def schema(self,table):
        # Names are exclusively from MODEL_TABLES, never from an upload or model.
        if self.store.url:
            rows=self.store.conn.execute("SELECT column_name,data_type FROM information_schema.columns WHERE table_schema='earthworks_lab' AND table_name=%s ORDER BY ordinal_position",(table,)).fetchall()
            return [{'name':name,'type':kind} for name,kind in rows]
        return [{'name':row[1],'type':row[2]} for row in self.store.conn.execute('PRAGMA table_info('+table+')').fetchall()]

    def overview(self):
        structures=[]
        for table,name,kind,objective in MODEL_TABLES:
            count=self.store.conn.execute('SELECT COUNT(*) FROM '+table).fetchone()[0]
            structures.append({'id':table,'name':name,'record_type':kind,'objective':objective,'records':count,'fields':self.schema(table),'origin':'Core model'})
        datasets=self.store.datasets.discover('9999-12-31')
        for item in datasets:
            p=self.store.datasets.placeholder
            links=self.store.conn.execute('SELECT COUNT(*) FROM dataset_entities WHERE dataset_id='+p+' AND version='+p,(item['id'],item['version'])).fetchone()[0]
            versions=self.store.conn.execute('SELECT COUNT(*) FROM datasets WHERE dataset_id='+p,(item['id'],)).fetchone()[0]
            field_types=item.get('field_types',{})
            if not field_types:
                row=self.store.conn.execute('SELECT payload FROM dataset_records WHERE dataset_id='+p+' AND version='+p+' LIMIT 1',(item['id'],item['version'])).fetchone()
                if row:
                    facts=self.store.datasets.decode(row[0])['facts']
                    field_types={key:[type(value).__name__] for key,value in facts.items()}
            original=self.store.conn.execute('SELECT filename FROM dataset_uploads WHERE dataset_id='+p+' AND version='+p,(item['id'],item['version'])).fetchone()
            definition=self.store.datasets.definition(item['id'],'9999-12-31',item['version'])
            item.update(entity_links=links,versions=versions,has_original=bool(original),field_definitions=definition['field_definitions'],undefined_fields=definition['undefined_fields'],fields=[{'name':name,'type':' / '.join(field_types.get(name,['unknown']))} for name in item['fact_fields']],graph_node='dataset:'+item['id']+'@'+item['version'])
        relations=[]
        for table,scope in [('context_edges','Commercial model'),('public_context_edges','Public context')]:
            relations.extend({'scope':scope,'relation':relation,'edges':count} for relation,count in self.store.conn.execute('SELECT relation,COUNT(*) FROM '+table+' GROUP BY relation ORDER BY relation').fetchall())
        join=' JOIN datasets d ON d.dataset_id=r.dataset_id AND d.version=r.version WHERE '+self.store.datasets.visibility_sql()
        records=self.store.conn.execute('SELECT COUNT(*) FROM dataset_records r'+join).fetchone()[0]
        links=self.store.conn.execute('SELECT COUNT(*) FROM dataset_entities r'+join).fetchone()[0]
        if records:
            relations.extend([{'scope':'Imported evidence','relation':'HAS_RECORD','edges':records},{'scope':'Imported evidence','relation':'SUPPORTED_BY','edges':records},{'scope':'Imported evidence','relation':'ABOUT_ENTITY','edges':links}])
        return {'structures':structures,'datasets':datasets,'relationships':relations,'limits':{'upload_bytes':MAX_UPLOAD_BYTES,'rows':MAX_IMPORT_ROWS},'backend':self.store.backend}

    def inspect(self,payload):
        rows,fields=parse_upload(payload.get('filename'),payload.get('content'))
        types={field:set() for field in fields}
        for row in rows:
            for field,value in row.items():
                kind='null' if value is None else 'boolean' if isinstance(value,bool) else 'integer' if isinstance(value,int) else 'number' if isinstance(value,float) else 'object' if isinstance(value,dict) else 'array' if isinstance(value,list) else 'text'
                types[field].add(kind)
        return {'records':len(rows),'fields':[{'name':f,'type':' / '.join(sorted(types[f]))} for f in fields],'sample':rows[:3],'note':'CSV values retain their original text.' if Path(payload['filename']).suffix.lower()=='.csv' else 'JSON value types are retained.'}

    def prepare(self,payload):
        rows,fields=parse_upload(payload.get('filename'),payload.get('content'))
        metadata=payload.get('metadata',{});mapping=payload.get('mapping',{})
        if not isinstance(metadata,dict) or not isinstance(mapping,dict):raise ValueError('Supply dataset details and field mapping')
        for key in ['id','version']:identifier(metadata.get(key))
        for key in ['name','objective','record_type']:
            if not isinstance(metadata.get(key),str) or not 1<=len(metadata[key].strip())<=800:raise ValueError('Supply a short '+key.replace('_',' '))
        available=day(metadata.get('available_date'))
        if metadata.get('data_kind') not in ['synthetic','public','private']:raise ValueError('Choose the evidence kind')
        allowed={'id','text','entities','effective_date','available_date','source_url'}
        if set(mapping)-allowed or any(value and value not in fields for value in mapping.values()):raise ValueError('Choose mappings from the uploaded fields')
        definitions=metadata.get('field_definitions',{})
        if not isinstance(definitions,dict) or set(definitions)-set(fields):raise ValueError('Field definitions must refer to uploaded fields')
        if len(canonical(definitions))>12000:raise ValueError('Keep the data dictionary within 12,000 bytes')
        for definition in definitions.values():
            if not isinstance(definition,dict) or set(definition)-{'meaning','unit','value_codes'} or any(not isinstance(value,str) or len(value)>500 for value in definition.values()):raise ValueError('Use short text for field meaning, units and value codes')
        source_url=metadata.get('source_url','')
        if source_url and (not isinstance(source_url,str) or not source_url.startswith(('https://','http://')) or len(source_url)>1500):raise ValueError('Source URL must be an HTTP(S) URL')
        known={kind:{r[0] for r in self.store.conn.execute('SELECT id FROM '+table).fetchall()} for kind,table in [('P','projects'),('V','vendors'),('Q','quotes')]}
        external=set();records=[]
        filename=Path(payload['filename']).name
        def cell(row,key,default=None):
            field=mapping.get(key)
            return row.get(field,default) if field else default
        for number,row in enumerate(rows,1):
            value=cell(row,'entities',[])
            refs=value if isinstance(value,list) else re.split(r'[,;|]',value) if isinstance(value,str) else [] if value in [None,''] else None
            if refs is None:raise ValueError('Entity links must be IDs or a list of IDs')
            if any(not isinstance(ref,str) for ref in refs):raise ValueError('Each entity ID must be text')
            refs=list(dict.fromkeys(ref.strip() for ref in refs if isinstance(ref,str) and ref.strip()))
            for ref in refs:
                if re.fullmatch(r'[PV]\d{3}|Q\d{4}',ref):
                    if ref not in known[ref[0]]:raise ValueError('Unknown core entity '+ref+'; choose an existing ID')
                elif re.fullmatch(r'[a-z][a-z0-9_-]*:[^\s]{1,100}',ref) and not ref.startswith(('dataset:','source:')):
                    external.add(ref)
                else:raise ValueError('Link an existing P/V/Q ID, or a namespaced external ID such as region:Brisbane')
            identity=cell(row,'id')
            identity='R'+str(number).zfill(6) if identity in [None,''] else str(identity)
            identifier(identity)
            text=cell(row,'text')
            text=str(text) if text is not None else '; '.join(str(k)+': '+json.dumps(v,ensure_ascii=False) for k,v in row.items())
            uri=cell(row,'source_url',source_url) or 'upload:'+filename
            if not isinstance(uri,str) or (not uri.startswith(('https://','http://','upload:'))) or len(uri)>1500:raise ValueError('Mapped source URLs must be HTTP(S) URLs')
            record={'id':identity,'text':text[:1500],'facts':row,'entities':refs,'available_date':day(cell(row,'available_date',available)),
                'source':{'uri':uri,'locator':filename+' · record '+str(number),'original_sha256':hashlib.sha256(payload['content'].encode()).hexdigest()}}
            effective=cell(row,'effective_date')
            if effective:record['effective_date']=day(effective)
            records.append(record)
        manifest={'id':metadata['id'],'version':metadata['version'],'name':metadata['name'].strip(),'description':metadata['objective'].strip(),'objective':metadata['objective'].strip(),'record_type':metadata['record_type'].strip(),'data_kind':metadata['data_kind'],'available_date':available,'records_file':'records.jsonl','field_definitions':definitions,'original_filename':filename,'original_sha256':hashlib.sha256(payload['content'].encode()).hexdigest()}
        manifest_bytes=canonical(manifest)
        raw=b'\n'.join(canonical(row) for row in records)+b'\n'
        saved,validated=DatasetCatalog.prepare(manifest_bytes,raw)
        p=self.store.datasets.placeholder
        existing=self.store.conn.execute('SELECT manifest FROM datasets WHERE dataset_id='+p+' AND version='+p,(manifest['id'],manifest['version'])).fetchone()
        if existing and self.store.datasets.decode(existing[0])['import_digest']!=saved['import_digest']:raise ValueError('This dataset version already exists with different content; use a new version')
        edges=[]
        dataset_node='dataset:'+manifest['id']+'@'+manifest['version']
        for row in validated[:3]:
            record_node='DATA:'+manifest['id']+':'+manifest['version']+':'+row['id']
            edges.append({'src':dataset_node,'relation':'HAS_RECORD','dst':record_node})
            edges.extend({'src':record_node,'relation':'ABOUT_ENTITY','dst':ref} for ref in row.get('entities',[]))
        preview={'id':manifest['id'],'version':manifest['version'],'name':manifest['name'],'records':len(validated),'fields':[{'name':f,'type':' / '.join(saved['field_types'][f])} for f in saved['fact_fields']],
            'entity_links':sum(len(r.get('entities',[])) for r in validated),'new_external_entities':sorted(external),'sample':validated[:3],'graph_preview':edges,'preview_digest':saved['import_digest'],'already_imported':bool(existing),'graph_node':dataset_node,
            'field_definitions':definitions,'undefined_fields':[f for f in fields if not definitions.get(f,{}).get('meaning')],
            'note':'Records become searchable evidence. Existing pricing calculations are unchanged.'}
        return preview,manifest_bytes,raw

    def preview(self,payload):return self.prepare(payload)[0]

    def commit(self,payload):
        preview,manifest,raw=self.prepare(payload)
        if payload.get('preview_digest')!=preview['preview_digest']:raise ValueError('Preview this exact file and mapping before importing')
        # A dedicated connection keeps the live agent outside the write transaction.
        from .store import Store
        with IMPORT_LOCK:
            writer=Store(path=self.store.path,database_url=self.store.url)
            try:
                result=writer.datasets.import_bytes(manifest,raw,upload={'filename':Path(payload['filename']).name,'content':payload['content'].encode()})
            finally:writer.close()
        return {**result,'graph_node':preview['graph_node'],'searchable':True}

    def graph(self,entity):
        if not isinstance(entity,str) or not 1<=len(entity)<=400 or any(ord(c)<32 for c in entity):raise ValueError('Supply a short entity ID')
        links=self.store.graph(entity)
        return {'entity':entity,'edges':links[:100],'limited':len(links)>100}

    def source(self,dataset,version):
        identifier(dataset);identifier(version)
        self.store.datasets.definition(dataset,'9999-12-31',version)
        p=self.store.datasets.placeholder
        row=self.store.conn.execute('SELECT filename,sha256,content FROM dataset_uploads WHERE dataset_id='+p+' AND version='+p,(dataset,version)).fetchone()
        if not row:raise ValueError('No uploaded original is stored for this dataset version')
        return {'filename':row[0],'sha256':row[1],'content':bytes(row[2]).decode('utf-8')}

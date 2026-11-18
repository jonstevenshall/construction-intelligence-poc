"""Versioned evidence envelopes: a new dataset needs data, not another SQL schema.

The importer is an operator command, never an agent tool. Search is read-only.
"""
import argparse
import hashlib
import json
import re
from array import array
from datetime import date,datetime,timezone
from pathlib import Path

from .store import INDEX_VERSION, embed, vector_literal


def identifier(value):
    if not isinstance(value,str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,79}",value):
        raise ValueError("Dataset, version and record IDs must be short identifiers")
    return value


class DatasetCatalog:
    def __init__(self,store):
        self.store=store
        self.conn=store.conn
        self.pg=bool(store.url)
        self.allow_private=True
        self.placeholder="%s" if self.pg else "?"
        payload_type="jsonb" if self.pg else "TEXT"
        vector_type="vector(384)" if self.pg else "BLOB"
        binary_type="BYTEA" if self.pg else "BLOB"
        for statement in [
            "CREATE TABLE IF NOT EXISTS datasets(dataset_id TEXT,version TEXT,available_date TEXT,manifest "+payload_type+",PRIMARY KEY(dataset_id,version))",
            "CREATE TABLE IF NOT EXISTS dataset_records(dataset_id TEXT,version TEXT,record_id TEXT,effective_date TEXT,available_date TEXT,payload "+payload_type+",text TEXT,index_version TEXT,embedding "+vector_type+",PRIMARY KEY(dataset_id,version,record_id),FOREIGN KEY(dataset_id,version) REFERENCES datasets(dataset_id,version))",
            "CREATE TABLE IF NOT EXISTS dataset_entities(dataset_id TEXT,version TEXT,record_id TEXT,entity_id TEXT,PRIMARY KEY(dataset_id,version,record_id,entity_id),FOREIGN KEY(dataset_id,version,record_id) REFERENCES dataset_records(dataset_id,version,record_id))",
            "CREATE TABLE IF NOT EXISTS dataset_uploads(dataset_id TEXT,version TEXT,filename TEXT,sha256 TEXT,content "+binary_type+",PRIMARY KEY(dataset_id,version),FOREIGN KEY(dataset_id,version) REFERENCES datasets(dataset_id,version))",
            "CREATE INDEX IF NOT EXISTS dataset_dates ON dataset_records(dataset_id,version,available_date,effective_date)",
            "CREATE INDEX IF NOT EXISTS dataset_entity_lookup ON dataset_entities(entity_id,dataset_id,version,record_id)"]:
            self.conn.execute(statement)
        if not self.pg:
            self.conn.commit()

    @staticmethod
    def decode(value):
        return value if isinstance(value,dict) else json.loads(value)

    def visibility_sql(self,alias="d"):
        if self.allow_private:return "1=1"
        field=alias+".manifest->>'data_kind'" if self.pg else "json_extract("+alias+".manifest,'$.data_kind')"
        return field+" <> 'private'"

    @staticmethod
    def prepare(manifest_bytes,raw):
        manifest=json.loads(manifest_bytes)
        required={"id","version","name","description","data_kind","available_date","records_file"}
        if not isinstance(manifest,dict) or not required<=set(manifest):
            raise ValueError("Incomplete dataset manifest")
        dataset,version=identifier(manifest["id"]),identifier(manifest["version"])
        date.fromisoformat(manifest["available_date"])
        if manifest["data_kind"] not in ["synthetic","public","private"]:
            raise ValueError("Declare synthetic, public or private evidence")
        if any(not isinstance(manifest[key],str) or len(manifest[key])>800 for key in ["name","description"]):
            raise ValueError("Use a short name and description")
        filename=manifest["records_file"]
        if not isinstance(filename,str) or Path(filename).name!=filename or not filename.endswith(".jsonl"):
            raise ValueError("records_file must name a local JSONL file")
        digest=hashlib.sha256(manifest_bytes+b"\n"+raw).hexdigest()
        rows=[]
        seen=set()
        fields=set()
        source_digest=hashlib.sha256(raw).hexdigest()
        for line_number,line in enumerate(raw.splitlines(),1):
            if not line.strip():
                continue
            row=json.loads(line)
            if not isinstance(row,dict) or not {"id","text","facts","source","available_date"}<=set(row):
                raise ValueError("Each evidence record needs id, text, facts, source and available_date")
            record_id=identifier(row["id"])
            if record_id in seen:
                raise ValueError("Duplicate record ID")
            seen.add(record_id)
            if not isinstance(row["text"],str) or not isinstance(row["facts"],dict) or not isinstance(row["source"],dict) or not isinstance(row["source"].get("uri"),str):
                raise ValueError("Each record needs text, a facts object and a source URI")
            if len(line)>6000:
                raise ValueError("Split evidence into records of at most 6,000 UTF-8 bytes")
            date.fromisoformat(row["available_date"])
            if row.get("effective_date"):
                date.fromisoformat(row["effective_date"])
            entities=row.get("entities",[])
            if not isinstance(entities,list) or len(entities)>20 or any(not isinstance(e,str) or len(e)>120 for e in entities):
                raise ValueError("Invalid entity references")
            fields.update(row["facts"])
            rows.append({**row,"import_provenance":{"file":filename,"line":line_number,"sha256":source_digest}})
        if not rows:
            raise ValueError("Dataset is empty")
        saved={**manifest,"record_count":len(rows),"fact_fields":sorted(fields),"import_digest":digest,"index_version":INDEX_VERSION}
        schema={}
        for row in rows:
            for field,value in row["facts"].items():
                kind="null" if value is None else "boolean" if isinstance(value,bool) else "integer" if isinstance(value,int) else "number" if isinstance(value,float) else "object" if isinstance(value,dict) else "array" if isinstance(value,list) else "text"
                schema.setdefault(field,set()).add(kind)
        saved["field_types"]={field:sorted(kinds) for field,kinds in schema.items()}
        return saved,rows

    def import_directory(self,directory):
        directory=Path(directory)
        manifest_bytes=(directory/"manifest.json").read_bytes()
        manifest=json.loads(manifest_bytes)
        filename=manifest.get("records_file","")
        if not isinstance(filename,str) or Path(filename).name!=filename or not filename.endswith(".jsonl"):
            raise ValueError("records_file must name a local JSONL file")
        return self.import_bytes(manifest_bytes,(directory/filename).read_bytes())

    def import_bytes(self,manifest_bytes,raw,upload=None):
        saved,rows=self.prepare(manifest_bytes,raw)
        dataset,version,digest=saved["id"],saved["version"],saved["import_digest"]
        existing=self.conn.execute("SELECT manifest FROM datasets WHERE dataset_id="+self.placeholder+" AND version="+self.placeholder,(dataset,version)).fetchone()
        if existing:
            previous=self.decode(existing[0])
            if previous["import_digest"]!=digest:
                raise ValueError("This evidence version is immutable; import a new version")
            return {"status":"already imported","id":dataset,"version":version,"records":previous["record_count"]}
        manifest=saved
        saved["imported_at"]=datetime.now(timezone.utc).isoformat()
        transaction=self.conn.transaction() if self.pg else self.conn
        with transaction:
            sql="INSERT INTO datasets VALUES (%s,%s,%s,%s::jsonb)" if self.pg else "INSERT INTO datasets VALUES (?,?,?,?)"
            self.conn.execute(sql,(dataset,version,manifest["available_date"],json.dumps(saved)))
            for row in rows:
                text=row["text"]+"\n"+json.dumps(row["facts"],ensure_ascii=False)
                values=(dataset,version,row["id"],row.get("effective_date"),row["available_date"],json.dumps(row,ensure_ascii=False),text,INDEX_VERSION)
                sql="INSERT INTO dataset_records VALUES (%s,%s,%s,%s,%s,%s::jsonb,%s,%s,%s::vector)" if self.pg else "INSERT INTO dataset_records VALUES (?,?,?,?,?,?,?,?,?)"
                vector=vector_literal(embed(text)) if self.pg else array("f",embed(text)).tobytes()
                self.conn.execute(sql,(*values,vector))
                for entity in dict.fromkeys(row.get("entities",[])):
                    self.store._insert("dataset_entities",(dataset,version,row["id"],entity))
            if upload:
                self.store._insert("dataset_uploads",(dataset,version,upload["filename"],hashlib.sha256(upload["content"]).hexdigest(),upload["content"]))
        return {"status":"imported","id":dataset,"version":version,"records":len(rows),"entity_links":sum(len(set(r.get("entities",[]))) for r in rows)}

    def discover(self,as_of):
        date.fromisoformat(as_of)
        rows=self.conn.execute("SELECT manifest FROM datasets d WHERE available_date<="+self.placeholder+" AND "+self.visibility_sql()+" ORDER BY available_date DESC,version DESC",(as_of,)).fetchall()
        latest={}
        manifests=[self.decode(row[0]) for row in rows]
        for manifest in sorted(manifests,key=lambda m:(m["available_date"],m.get("imported_at",""),m["version"]),reverse=True):
            latest.setdefault(manifest["id"],manifest)
        return [{**{key:m[key] for key in ["id","version","name","description","data_kind","available_date","record_count","fact_fields","index_version"]},"objective":m.get("objective",m["description"]),"record_type":m.get("record_type","Evidence"),"field_types":m.get("field_types",{})} for m in latest.values()]

    def get(self,dataset,version,record_id):
        for value in [dataset,version,record_id]:
            identifier(value)
        if not self.allow_private:self.definition(dataset,"9999-12-31",version)
        row=self.conn.execute("SELECT payload FROM dataset_records WHERE dataset_id="+self.placeholder+" AND version="+self.placeholder+" AND record_id="+self.placeholder,(dataset,version,record_id)).fetchone()
        if not row:
            raise ValueError("Unknown evidence record")
        return self.decode(row[0])

    def definition(self,dataset,as_of,version=None):
        identifier(dataset)
        if version is None:
            found=next((item for item in self.discover(as_of) if item["id"]==dataset),None)
            if found is None:raise ValueError("No dataset version available by this date")
            version=found["version"]
        identifier(version)
        row=self.conn.execute("SELECT manifest FROM datasets d WHERE dataset_id="+self.placeholder+" AND version="+self.placeholder+" AND available_date<="+self.placeholder+" AND "+self.visibility_sql(),(dataset,version,as_of)).fetchone()
        if not row:raise ValueError("Unknown or unavailable dataset version")
        manifest=self.decode(row[0]);definitions=manifest.get("field_definitions",{})
        return {"id":dataset,"version":version,"record_type":manifest.get("record_type","Evidence"),"objective":manifest.get("objective",manifest["description"]),
            "data_kind":manifest["data_kind"],"fields":manifest["fact_fields"],"field_types":manifest.get("field_types",{}),"field_definitions":definitions,
            "undefined_fields":[field for field in manifest["fact_fields"] if not definitions.get(field,{}).get("meaning")],
            "basis":"Definitions are declared by the uploader. Missing units/code meanings are unknown; no pricing or regulatory rule is installed by importing evidence."}

    def graph(self,entity):
        p=self.placeholder
        params=[]
        if entity.startswith("dataset:") and "@" in entity:
            dataset,version=entity[8:].split("@",1)
            where="r.dataset_id="+p+" AND r.version="+p;params=[dataset,version]
        elif entity.startswith("DATA:") and len(entity.split(":"))==4:
            _,dataset,version,record=entity.split(":")
            where="r.dataset_id="+p+" AND r.version="+p+" AND r.record_id="+p;params=[dataset,version,record]
        else:
            where="EXISTS(SELECT 1 FROM dataset_entities e WHERE e.dataset_id=r.dataset_id AND e.version=r.version AND e.record_id=r.record_id AND e.entity_id="+p+")";params=[entity]
        rows=self.conn.execute("SELECT r.dataset_id,r.version,r.record_id,r.payload FROM dataset_records r JOIN datasets d ON d.dataset_id=r.dataset_id AND d.version=r.version WHERE ("+where+") AND "+self.visibility_sql()+" ORDER BY r.dataset_id,r.version,r.record_id LIMIT 25",params).fetchall()
        edges=[]
        for dataset,version,record_id,payload in rows:
            record=self.decode(payload)
            node="DATA:"+dataset+":"+version+":"+record_id
            metadata={"source_kind":"imported","dataset_id":dataset,"version":version,"record_id":record_id,"source_uri":record["source"]["uri"]}
            edges.append({"src":"dataset:"+dataset+"@"+version,"relation":"HAS_RECORD","dst":node,**metadata})
            edges.extend({"src":node,"relation":"ABOUT_ENTITY","dst":ref,**metadata} for ref in record.get("entities",[]))
            source="source:"+hashlib.sha256(record["source"]["uri"].encode()).hexdigest()[:16]
            edges.append({"src":node,"relation":"SUPPORTED_BY","dst":source,**metadata})
        return edges

    def search(self,query,as_of,dataset_id=None,entity_id=None,limit=3):
        catalog=self.discover(as_of)
        if not isinstance(query,str) or len(query)>600:
            raise ValueError("Dataset search must be short text")
        if entity_id is not None and (not isinstance(entity_id,str) or len(entity_id)>120):
            raise ValueError("Invalid entity reference")
        selected=[m for m in catalog if dataset_id is None or m["id"]==dataset_id]
        if not selected or not query.strip():
            return {"datasets":catalog[:20],"matches":[]}
        p=self.placeholder
        clauses=["("+" OR ".join("(r.dataset_id="+p+" AND r.version="+p+")" for _ in selected)+")","r.available_date<="+p,"(r.effective_date IS NULL OR r.effective_date<="+p+")","r.index_version="+p]
        params=[value for m in selected for value in [m["id"],m["version"]]]+[as_of,as_of,INDEX_VERSION]
        if entity_id:
            clauses.append("EXISTS(SELECT 1 FROM dataset_entities e WHERE e.dataset_id=r.dataset_id AND e.version=r.version AND e.record_id=r.record_id AND e.entity_id="+p+")")
            params.append(entity_id)
        where=" AND ".join(clauses)
        vector=embed(query)
        terms=list(dict.fromkeys(re.findall(r"[a-z0-9_]+",query.lower())))[:10]
        limit=max(1,min(int(limit),3))
        if self.pg:
            # Exact term overlap also protects single-word queries from signed-hash
            # collisions. This is still lexical retrieval, not semantic matching.
            overlap="+("+"+".join("CASE WHEN position(%s in lower(text))>0 THEN 1.0 ELSE 0 END" for _ in terms)+")/"+str(len(terms)) if terms else ""
            rows=self.conn.execute("WITH eligible AS MATERIALIZED(SELECT r.* FROM dataset_records r WHERE "+where+") SELECT dataset_id,version,record_id,payload,1-(embedding <=> %s::vector)"+overlap+" AS score FROM eligible ORDER BY score DESC LIMIT %s",(*params,vector_literal(vector),*terms,limit)).fetchall()
        else:
            candidates=self.conn.execute("SELECT r.dataset_id,r.version,r.record_id,r.payload,r.embedding FROM dataset_records r WHERE "+where,params).fetchall()
            scored=[]
            for row in candidates:
                stored=array("f");stored.frombytes(row[-1])
                payload=self.decode(row[3])
                text=(payload["text"]+"\n"+json.dumps(payload["facts"],ensure_ascii=False)).lower()
                overlap=sum(term in text for term in terms)/len(terms) if terms else 0
                scored.append((*row[:4],sum(a*b for a,b in zip(vector,stored))+overlap))
            rows=sorted(scored,key=lambda r:r[-1],reverse=True)[:limit]
        kinds={m["id"]:m["data_kind"] for m in selected}
        matches=[{"dataset_id":r[0],"version":r[1],"record_id":r[2],"data_kind":kinds[r[0]],"record":self.decode(r[3]),"score":r[4]} for r in rows if r[4]>0]
        return {"datasets":catalog[:20],"matches":matches,"retrieval_basis":"Lexical vectors plus term overlap, exact date/entity filters; relevance does not establish applicability or causality"}


def main():
    from .config import load_local_env
    from .store import Store
    load_local_env()
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory",type=Path)
    args=parser.parse_args()
    store=Store()
    try:
        print(json.dumps(DatasetCatalog(store).import_directory(args.directory),indent=2))
    finally:
        store.close()


if __name__=="__main__":
    main()

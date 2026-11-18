"""Structured records plus explicit lexical vectors; PostgreSQL/pgvector or local SQLite."""
import hashlib
import json
import math
import os
import re
import sqlite3
from array import array
from pathlib import Path

from .corpus import ROOT, load

DIMENSIONS = 384
INDEX_VERSION = "signed-hash-lexical-v1-384"
ALIASES = {"upfront":"deposit", "advance":"deposit", "deposits":"deposit", "cheapest":"price", "cheap":"price",
           "cost":"price", "costs":"price", "expensive":"price", "exclusions":"excluded", "exclude":"excluded",
           "omitted":"excluded", "missing":"excluded", "gaps":"excluded", "depot":"mobilisation",
           "mobilization":"mobilisation", "haulage":"haul", "distances":"distance", "optional":"optional"}
STOP = set("a an the of for to is are be this that it with and or what which how their they does do can should please".split())


def embed(text):
    """Free offline lexical baseline. This is NOT a neural semantic embedding model."""
    tokens=[ALIASES.get(t,t) for t in re.findall(r"[a-z0-9]+",text.lower()) if t not in STOP]
    features=tokens+[a+"_"+b for a,b in zip(tokens,tokens[1:])]
    values=[0.0]*DIMENSIONS
    for word in features:
        key=int.from_bytes(hashlib.blake2b(word.encode(),digest_size=8).digest(),"big")
        values[key%DIMENSIONS] += 1.0 if key & (1<<63) else -1.0
    norm=math.sqrt(sum(v*v for v in values)) or 1
    return [v/norm for v in values]


def vector_literal(values):
    return "["+",".join(format(v,".8f") for v in values)+"]"


class Store:
    def __init__(self, path=None, database_url=None):
        self.url=database_url if database_url is not None else os.getenv("DATABASE_URL","")
        self.path=Path(path or ROOT/"var"/"earthworks.sqlite")
        self.backend="postgres-pgvector" if self.url else "sqlite-local-vectors"
        if self.url:
            try:
                import psycopg
            except ImportError as exc:
                raise RuntimeError("Install requirements-postgres.txt to use DATABASE_URL") from exc
            self.conn=psycopg.connect(self.url,autocommit=True)
        else:
            self.path.parent.mkdir(parents=True,exist_ok=True)
            self.conn=sqlite3.connect(self.path,check_same_thread=False)
        self._schema()
        from .datasets import DatasetCatalog
        self.datasets=DatasetCatalog(self)

    def _schema(self):
        if self.url:
            self.conn.execute("CREATE SCHEMA IF NOT EXISTS earthworks_lab")
            self.conn.execute("SET search_path TO earthworks_lab, public")
            self.conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
            self.conn.execute("CREATE TABLE IF NOT EXISTS records(kind text, id text, payload jsonb NOT NULL, PRIMARY KEY(kind,id))")
            self.conn.execute("CREATE TABLE IF NOT EXISTS chunks(id text PRIMARY KEY, project_id text, quote_date text, quote_id text, source_path text, source_line integer, text text, index_version text, embedding vector(384))")
            self.conn.execute("CREATE INDEX IF NOT EXISTS chunks_embedding_idx ON chunks USING hnsw(embedding vector_cosine_ops)")
        else:
            self.conn.executescript("""
              CREATE TABLE IF NOT EXISTS records(kind TEXT,id TEXT,payload TEXT NOT NULL,PRIMARY KEY(kind,id));
              CREATE TABLE IF NOT EXISTS chunks(id TEXT PRIMARY KEY,project_id TEXT,quote_date TEXT,quote_id TEXT,source_path TEXT,source_line INTEGER,text TEXT,index_version TEXT,embedding BLOB);
              CREATE INDEX IF NOT EXISTS chunks_project ON chunks(project_id,quote_date);
            """)
        definitions=[
          "CREATE TABLE IF NOT EXISTS projects(id TEXT PRIMARY KEY,suburb TEXT,tender_date TEXT,start_date TEXT,area_m2 BIGINT)",
          "CREATE TABLE IF NOT EXISTS vendors(id TEXT PRIMARY KEY,name TEXT,depot_suburb TEXT)",
          "CREATE TABLE IF NOT EXISTS quotes(id TEXT PRIMARY KEY,project_id TEXT REFERENCES projects(id),vendor_id TEXT REFERENCES vendors(id),quote_date TEXT,total_ex_cents BIGINT,total_inc_cents BIGINT,optional_cents BIGINT,deposit_percent INTEGER,deposit_cents BIGINT,pattern TEXT)",
          "CREATE TABLE IF NOT EXISTS quote_lines(id TEXT PRIMARY KEY,quote_id TEXT REFERENCES quotes(id),scope_id TEXT,status TEXT,quantity DOUBLE PRECISION,unit TEXT,rate_cents BIGINT,amount_cents BIGINT,source_line INTEGER)",
          "CREATE TABLE IF NOT EXISTS context_edges(src TEXT,relation TEXT,dst TEXT,evidence_path TEXT,evidence_line INTEGER,PRIMARY KEY(src,relation,dst))",
          "CREATE INDEX IF NOT EXISTS quotes_project ON quotes(project_id)",
          "CREATE INDEX IF NOT EXISTS quotes_date ON quotes(quote_date)",
          "CREATE INDEX IF NOT EXISTS lines_scope ON quote_lines(scope_id,status)",
          "CREATE INDEX IF NOT EXISTS edges_destination ON context_edges(dst,relation)"]
        definitions.extend([
          "CREATE TABLE IF NOT EXISTS public_sources(id TEXT PRIMARY KEY,url TEXT,kind TEXT,retrieved_at TEXT,metadata TEXT)",
          "CREATE TABLE IF NOT EXISTS weather_cells(id TEXT PRIMARY KEY,latitude DOUBLE PRECISION,longitude DOUBLE PRECISION)",
          "CREATE TABLE IF NOT EXISTS weather_locations(suburb TEXT PRIMARY KEY,cell_id TEXT REFERENCES weather_cells(id),latitude DOUBLE PRECISION,longitude DOUBLE PRECISION)",
          "CREATE TABLE IF NOT EXISTS weather_days(cell_id TEXT REFERENCES weather_cells(id),day TEXT,precipitation_mm DOUBLE PRECISION,PRIMARY KEY(cell_id,day))",
          "CREATE TABLE IF NOT EXISTS diesel_prices(day TEXT PRIMARY KEY,cents_per_litre_inc_gst DOUBLE PRECISION,source_cell TEXT)",
          "CREATE TABLE IF NOT EXISTS soil_screenings(suburb TEXT PRIMARY KEY,soil_order TEXT,clay_percent DOUBLE PRECISION,payload TEXT)",
          "CREATE TABLE IF NOT EXISTS public_context_edges(src TEXT,relation TEXT,dst TEXT,source_id TEXT,url TEXT,PRIMARY KEY(src,relation,dst))",
          "CREATE TABLE IF NOT EXISTS context_metadata(key TEXT PRIMARY KEY,value TEXT)",
          "CREATE INDEX IF NOT EXISTS weather_day_idx ON weather_days(day)"])
        for statement in definitions:
            self.conn.execute(statement)
        if not self.url:
            self.conn.commit()

    def _insert(self,table,values):
        # table names are internal constants, never supplied by a client or model.
        placeholder="%s" if self.url else "?"
        self.conn.execute("INSERT INTO "+table+" VALUES ("+",".join([placeholder]*len(values))+")",values)

    def ingest(self, data_dir=ROOT/"data"):
        data=load(Path(data_dir))
        # Dedicated generated corpus store: reindex it as one transaction.
        if self.url:
            transaction=self.conn.transaction()
        else:
            transaction=self.conn
        with transaction:
            self.conn.execute("DELETE FROM chunks")
            self.conn.execute("DELETE FROM records")
            for table in ["context_edges","quote_lines","quotes","vendors","projects"]:
                self.conn.execute("DELETE FROM "+table)
            for project in data["projects"]:
                self._insert("projects",(project["id"],project["suburb"],project["tender_date"],project["planned_start_date"],project["site_area_m2"]))
            for vendor in data["vendors"]:
                self._insert("vendors",(vendor["id"],vendor["name"],vendor["depot_suburb"]))
            for kind, rows in data.items():
                for row in rows:
                    sql="INSERT INTO records VALUES (%s,%s,%s::jsonb)" if self.url else "INSERT INTO records VALUES (?,?,?)"
                    self.conn.execute(sql,(kind,row["id"],json.dumps(row)))
            for quote in data["quotes"]:
                self._insert("quotes",(quote["id"],quote["project_id"],quote["vendor_id"],quote["quote_date"],quote["contract_ex_gst_cents"],quote["contract_inc_gst_cents"],quote["optional_ex_gst_cents"],quote["deposit_percent"],quote["deposit_cents"],quote["scenario_pattern"]))
                for line in quote["lines"]:
                    self._insert("quote_lines",(line["id"],quote["id"],line["scope_item_id"],line["status"],line["quantity"],line["unit"],line["rate_cents"],line["amount_cents"],line["evidence"]["line"]))
                    self._insert("context_edges",(quote["id"],"HAS_LINE",line["id"],quote["document_path"],line["evidence"]["line"]))
                    self._insert("context_edges",(line["id"],"PRICES_SCOPE",line["scope_item_id"],quote["document_path"],line["evidence"]["line"]))
                for src,relation,dst in [(quote["project_id"],"HAS_QUOTE",quote["id"]),(quote["id"],"SUBMITTED_BY",quote["vendor_id"]),(quote["id"],"SUPPORTED_BY",quote["document_id"])]:
                    self._insert("context_edges",(src,relation,dst,quote["document_path"],1))
                path=Path(data_dir)/quote["document_path"]
                doc=path.read_text().splitlines()
                groups=[("overview",1,"\n".join(doc[:10])), ("terms",quote["terms_evidence"][0]["line"],"\n".join(quote["terms"]))]
                for zone in dict.fromkeys(line["zone"] for line in quote["lines"]):
                    lines=[line for line in quote["lines"] if line["zone"]==zone]
                    source_line=lines[0]["evidence"]["line"]
                    text="\n".join(doc[line["evidence"]["line"]-1] for line in lines)
                    groups.append((zone,source_line,text))
                for index,(section,source_line,text) in enumerate(groups):
                    content=f"{quote['id']} {quote['vendor_name']} {section}\n{text}"
                    values=(f"{quote['document_id']}-{index}",quote["project_id"],quote["quote_date"],quote["id"],quote["document_path"],source_line,content,INDEX_VERSION)
                    if self.url:
                        self.conn.execute("INSERT INTO chunks VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s::vector)",(*values,vector_literal(embed(content))))
                    else:
                        self.conn.execute("INSERT INTO chunks VALUES (?,?,?,?,?,?,?,?,?)",(*values,array("f",embed(content)).tobytes()))
        return {**{k:len(v) for k,v in data.items()},"chunks":self.conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0],"backend":self.backend,"embedding":INDEX_VERSION}

    def records(self,kind):
        sql="SELECT payload FROM records WHERE kind=%s ORDER BY id" if self.url else "SELECT payload FROM records WHERE kind=? ORDER BY id"
        rows=self.conn.execute(sql,(kind,)).fetchall()
        return [row[0] if isinstance(row[0],dict) else json.loads(row[0]) for row in rows]

    def search(self,query,project_id=None,as_of=None,limit=5):
        query=query[:2000]
        limit=max(1,min(int(limit),10))
        clauses=["index_version="+("%s" if self.url else "?")]
        params=[INDEX_VERSION]
        for column,value in [("project_id",project_id),("quote_date",as_of)]:
            if value:
                clauses.append(column+("<=" if column=="quote_date" else "=")+("%s" if self.url else "?"))
                params.append(value)
        where=" AND ".join(clauses)
        vector=embed(query)
        if self.url:
            # Exact search over eligible rows: avoid approximate-index filtering recall surprises.
            sql="WITH eligible AS MATERIALIZED (SELECT * FROM chunks WHERE "+where+") SELECT id,quote_id,source_path,source_line,text,1-(embedding <=> %s::vector) AS score FROM eligible ORDER BY embedding <=> %s::vector LIMIT %s"
            rows=self.conn.execute(sql,(*params,vector_literal(vector),vector_literal(vector),limit)).fetchall()
        else:
            candidates=self.conn.execute("SELECT id,quote_id,source_path,source_line,text,embedding FROM chunks WHERE "+where,params).fetchall()
            scored=[]
            for row in candidates:
                vec=array("f");vec.frombytes(row[-1])
                score=sum(a*b for a,b in zip(vector,vec))
                scored.append((*row[:5],score))
            rows=sorted(scored,key=lambda row:row[-1],reverse=True)[:limit]
        return [dict(zip(["id","quote_id","path","line","text","score"],row)) for row in rows if row[-1]>0]

    def close(self):
        self.conn.close()

    def graph(self,entity):
        placeholder="%s" if self.url else "?"
        rows=self.conn.execute("SELECT src,relation,dst,evidence_path,evidence_line FROM context_edges WHERE src="+placeholder+" OR dst="+placeholder+" LIMIT 80",(entity,entity)).fetchall()
        result=[dict(zip(["src","relation","dst","path","line"],row)) for row in rows]
        public=self.conn.execute("SELECT src,relation,dst,source_id,url FROM public_context_edges WHERE src="+placeholder+" OR dst="+placeholder+" LIMIT 20",(entity,entity)).fetchall()
        return result+[{**dict(zip(["src","relation","dst","source_id","source_url"],row)),"source_kind":"public"} for row in public]+self.datasets.graph(entity)

    def counts(self):
        return {table:self.conn.execute("SELECT COUNT(*) FROM "+table).fetchone()[0] for table in ["projects","vendors","quotes","quote_lines","chunks","context_edges"]}

    def public_counts(self):
        return {table:self.conn.execute("SELECT COUNT(*) FROM "+table).fetchone()[0] for table in ["public_sources","weather_cells","weather_days","diesel_prices","soil_screenings","public_context_edges"]}

    def _many(self,table,rows):
        if not rows:
            return
        placeholder="%s" if self.url else "?"
        cursor=self.conn.cursor()
        try:
            cursor.executemany("INSERT INTO "+table+" VALUES ("+",".join([placeholder]*len(rows[0]))+")",rows)
        finally:
            cursor.close()

    def ingest_public_context(self,directory=ROOT/"data"/"context",force=False):
        directory=Path(directory)
        manifest=directory/"manifest.json"
        if not manifest.exists():
            return {"status":"no public snapshots imported"}
        packs={name:json.loads((directory/(name+".json")).read_text()) for name in ["weather","diesel","soils"] if (directory/(name+".json")).exists()}
        digest=hashlib.sha256(b"".join(name.encode()+(directory/(name+".json")).read_bytes() for name in sorted(packs))).hexdigest()
        marker=self.conn.execute("SELECT value FROM context_metadata WHERE key='snapshot_digest'").fetchone()
        if marker and marker[0]==digest and not force:
            return {"status":"current snapshot already indexed",**self.public_counts()}
        transaction=self.conn.transaction() if self.url else self.conn
        with transaction:
            for table in ["public_context_edges","weather_days","weather_locations","weather_cells","diesel_prices","soil_screenings","public_sources","context_metadata"]:
                self.conn.execute("DELETE FROM "+table)
            for pack in packs.values():
                metadata={k:v for k,v in pack.items() if k not in ["records","cells","locations"]}
                self._insert("public_sources",(pack["source_id"],pack["source_url"],pack.get("data_type",pack.get("type","public context")),pack["retrieved_at"],json.dumps(metadata)))
            weather=packs.get("weather",{"cells":[],"locations":[]})
            self._many("weather_cells",[(c["id"],c["latitude"],c["longitude"]) for c in weather["cells"]])
            self._many("weather_locations",[(r["suburb"],r["cell_id"],*r["requested_coordinates"]) for r in weather["locations"]])
            self._many("weather_days",[(c["id"],day,value) for c in weather["cells"] for day,value in zip(c["time"],c["precipitation_mm"])])
            self._many("diesel_prices",[(r["date"],r["cents_per_litre_inc_gst"],r["source_cell"]) for r in packs.get("diesel",{}).get("records",[])])
            self._many("soil_screenings",[(r["suburb"],r["soil_order"],r["mapped_clay_percent_0_30cm"],json.dumps(r)) for r in packs.get("soils",{}).get("locations",[])])
            locations={r["suburb"]:r for r in weather["locations"]}
            soils={r["suburb"]:r for r in packs.get("soils",{}).get("locations",[])}
            for p in self.records("projects"):
                if p["suburb"] in locations:
                    self._insert("public_context_edges",(p["id"],"HAS_REGIONAL_WEATHER_CONTEXT",locations[p["suburb"]]["cell_id"],weather["source_id"],weather["documentation_url"]))
                if p["suburb"] in soils:
                    self._insert("public_context_edges",(p["id"],"HAS_REGIONAL_SOIL_SCREENING",p["suburb"],packs["soils"]["source_id"],soils[p["suburb"]]["source_url"]))
            if "diesel" in packs:
                for q in self.records("quotes"):
                    self._insert("public_context_edges",(q["id"],"HAS_RETROSPECTIVE_DIESEL_CONTEXT",packs["diesel"]["source_id"],packs["diesel"]["source_id"],packs["diesel"]["source_url"]))
            self._insert("context_metadata",("snapshot_digest",digest))
        return {"status":"imported snapshots indexed",**self.public_counts()}


if __name__=="__main__":
    store=Store()
    print(json.dumps({"corpus":store.ingest(),"public_context":store.ingest_public_context()},indent=2))

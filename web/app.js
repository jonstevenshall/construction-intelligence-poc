"use strict";
const $ = id => document.getElementById(id);
let accessToken = sessionStorage.getItem("earthworks-access") || "";
let selectedProject = null;
let packagePlan = null, evidenceLog = [], evidenceSources = [], referenceBids = {};
let projectRevision = 0;
let conversationBrief = {}, conversationHistory = [], lastConversation;
let workspaceUnlocked = false, modelReady = false, sendingMessage = false;
let workingEstimate = null, sourceMemory = [], latestCalculations = [];
let dataUpload = null, reviewedImport = null, uploadRevision = 0, importFormRevision = 0;
let simulationId = crypto.randomUUID(), pendingSavedSimulation = null;
let simulationOpen = false, importsAllowed = false;
const fmt = (c, decimals = 0) => new Intl.NumberFormat("en-AU", {style:"currency", currency:"AUD", minimumFractionDigits:decimals, maximumFractionDigits:decimals}).format(c / 100);
const number = value => new Intl.NumberFormat("en-AU", {maximumFractionDigits:2}).format(value);
const signedMoney = value => (value >= 0 ? "+" : "−") + fmt(Math.abs(value), 2);
function node(tag, text, cls) {
  const n = document.createElement(tag);
  if (text !== undefined) n.textContent = text;
  if (cls) n.className = cls;
  return n;
}
function clear(id) { $(id).replaceChildren(); }
function fail(error) { $("error").textContent = error.message || String(error); $("error").hidden = false; }
function updateConversationControls() {
  $("send-brief").disabled = !workspaceUnlocked || !modelReady || sendingMessage;
  ["job-message","agent-asof","example-brief","reset-conversation","resume-simulation","discard-simulation"].forEach(id => { $(id).disabled = !workspaceUnlocked || sendingMessage; });
}
function lockWorkspace(message) {
  workspaceUnlocked = false; modelReady = false; accessToken = "";
  sessionStorage.removeItem("earthworks-access");
  $("workspace").hidden = true; $("access").hidden = !simulationOpen; $("error").hidden = true;
  $("access-error").textContent = message; $("access-error").hidden = !message;
  $("status").textContent = "Private demo · unlock to begin";
  updateConversationControls(); if (simulationOpen) $("access-token").focus();
}
function link(text, url) {
  try { if (!["http:","https:"].includes(new URL(url).protocol)) return node("span",text); } catch { return node("span",text); }
  const a = node("a", text); a.href = url; a.target = "_blank"; a.rel = "noopener noreferrer"; return a;
}
function button(text, action, cls) {
  const b = node("button", text, cls); b.type = "button"; b.addEventListener("click", action); return b;
}
function table(headers, rows) {
  const wrap = node("div", undefined, "table-wrap"), t = node("table"), head = node("thead"), tr = node("tr");
  headers.forEach(text => tr.append(node("th", text))); head.append(tr); t.append(head);
  const body = node("tbody");
  rows.forEach(cells => {
    const row = node("tr");
    cells.forEach(content => { const cell = node("td"); cell.append(content instanceof Node ? content : document.createTextNode(String(content))); row.append(cell); });
    body.append(row);
  });
  t.append(body); wrap.append(t); return wrap;
}
function disclosure(title, content) {
  const d = node("details"); d.append(node("summary", title), content); return d;
}
async function api(path, body) {
  const options = {headers:{Authorization:"Bearer " + accessToken}};
  if (body !== undefined) { options.method = "POST"; options.headers["Content-Type"] = "application/json"; options.body = JSON.stringify(body); }
  const response = await fetch(path, options), result = await response.json();
  if (response.status === 401) { lockWorkspace("Enter the demo access token to continue. Check DEMO_ACCESS_TOKEN in Coolify if you don't have it."); const error = new Error("Demo access token was not accepted."); error.status = 401; throw error; }
  if (!response.ok) { const error = new Error(result.error || "Request failed"); error.code = result.code; throw error; }
  $("error").hidden = true; return result;
}
function sourceButton(qid, line, label) { return button(label || qid + (line ? " · L" + line : ""), () => openDocument(qid,line), "source-button"); }
async function openDocument(qid, line) {
  try {
    const doc = await api("/api/document/" + qid);
    $("document-title").textContent = qid + " · synthetic source bid"; clear("document-text");
    doc.lines.forEach((text,i) => {
      const row = node("span", String(i+1).padStart(3," ") + "  " + text, "document-line" + (i+1 === line ? " target" : ""));
      row.id = "source-line-" + (i+1); $("document-text").append(row);
    });
    $("document").showModal(); if (line) $("source-line-"+line)?.scrollIntoView({block:"center"});
  } catch (error) { fail(error); }
}
function showPanel(id) {
  document.querySelectorAll(".tab").forEach(b => { const active = b.dataset.panel === id; b.classList.toggle("active",active); b.setAttribute("aria-pressed",String(active)); });
  document.querySelectorAll(".panel").forEach(p => { p.hidden = p.id !== id; });
  if (id === "data") loadDataWorkbench().catch(dataFailure);
}
function dataFailure(error) { $("data-error").textContent = error.message || String(error); $("data-error").hidden = false; }
function dataDetail(title,content) { $("data-detail-title").textContent = title; $("data-detail-content").replaceChildren(content); $("data-detail").showModal(); }
async function loadDataWorkbench() {
  const data = await api("/api/data"), target = $("data-inventory"); target.replaceChildren(); $("data-error").hidden = true;
  target.append(node("h3","Model structures"),table(["Structure","Type","Objective","Records","Fields"],data.structures.map(item => [item.name,item.record_type,item.objective,number(item.records),button("Inspect",() => dataDetail(item.name,table(["Field","Type"],item.fields.map(f => [f.name,f.type]))))])));
  const sources = node("section",undefined,"data-sources"); sources.append(node("h3","Registered evidence datasets"));
  if (!data.datasets.length) sources.append(node("p","No additional datasets registered.","hint"));
  data.datasets.forEach(item => {
    const card = node("article",undefined,"live-evidence-card");
    card.append(node("h3",item.name),node("p",item.record_type+" · "+item.data_kind+" · "+number(item.record_count)+" records · "+number(item.entity_links)+" entity links","hint"),node("p",item.objective,"context-copy"),node("p",item.id+" / "+item.version+" · "+item.versions+" version(s) · available "+item.available_date,"hint"));
    const actions = node("div",undefined,"source-links");
    actions.append(button("Inspect fields",() => dataDetail(item.name,table(["Field","Type","Meaning","Unit","Value codes"],item.fields.map(f => { const d=item.field_definitions?.[f.name] || {}; return [f.name,f.type,d.meaning || "Undefined",d.unit || "—",d.value_codes || "—"]; })))),button("Explore graph",() => inspectDataGraph(item.graph_node).catch(dataFailure)));
    if (item.has_original) actions.append(button("Original file",async () => { try { const original = await api("/api/data/source/"+[item.id,item.version].map(encodeURIComponent).join("/")); const body=node("div"); body.append(node("p","SHA-256 "+original.sha256,"hash"),node("pre",original.content,"raw-fact")); dataDetail(original.filename,body); } catch(error) { dataFailure(error); } }));
    card.append(actions); sources.append(card);
  }); target.append(sources);
  target.append(disclosure("Graph relationship types",table(["Scope","Relationship","Edges"],data.relationships.map(r => [r.scope,r.relation,number(r.edges)]))));
}
function invalidateImport() { importFormRevision++; reviewedImport = null; $("data-preview").hidden = true; $("data-commit").hidden = true; $("data-commit").disabled = true; $("data-import-result").textContent = ""; }
async function readDataFile() {
  invalidateImport(); const revision = ++uploadRevision, file = $("data-file").files[0]; dataUpload = null; $("data-upload-fields").hidden = true;
  if (!file) return;
  try {
    if (file.size > 2000000) throw new Error("Choose a file smaller than 2 MB.");
    let content;
    try { content = new TextDecoder("utf-8",{fatal:true,ignoreBOM:true}).decode(await file.arrayBuffer()); }
    catch { throw new Error("Use a UTF-8 encoded CSV, JSON or JSONL file."); }
    const payload = {filename:file.name,content}, inspected = await api("/api/data/inspect",payload);
    if (revision !== uploadRevision) return; dataUpload = payload;
    $("data-file-summary").textContent = number(inspected.records)+" records · "+inspected.fields.length+" fields. "+inspected.note;
    const stem = file.name.replace(/\.[^.]+$/,""); $("data-name").value = stem;
    $("data-id").value = stem.toLowerCase().replace(/[^a-z0-9_.-]+/g,"-").replace(/^[^a-z0-9]+/,"").slice(0,80);
    const now = new Date(), today = new Date(now.getTime()-now.getTimezoneOffset()*60000).toISOString().slice(0,10);
    $("data-version").value = today; $("data-available").value = today;
    clear("data-mapping"); const names = inspected.fields.map(f => f.name);
    const roles = {id:["Record ID","Generate stable IDs"],text:["Searchable description","Build from record fields"],entities:["Entity links","No project/supplier link"],effective_date:["Effective date","No effective date"],available_date:["Record availability","Use dataset availability"],source_url:["Source URL column","Use source URL or uploaded file"]};
    Object.entries(roles).forEach(([key,[label,automatic]]) => {
      const field = node("label",label), select = node("select"), option = node("option",automatic); select.id = "data-map-"+key; option.value = ""; select.append(option);
      inspected.fields.forEach(f => { const choice=node("option",f.name+" · "+f.type); choice.value=f.name; select.append(choice); });
      if (names.includes(key)) select.value = key;
      else if (key === "entities" && names.includes("project_id")) select.value = "project_id";
      field.append(select); $("data-mapping").append(field);
    });
    $("data-dictionary").replaceChildren(table(["Field / type","Meaning","Unit","Value codes"],inspected.fields.map(f => {
      const cells=[f.name+" · "+f.type];
      [["meaning","What does this field represent?"],["unit","If applicable"],["value_codes","Explain encoded values, if any"]].forEach(([key,placeholder]) => {
        const input=node("input"); input.type="text"; input.maxLength=500; input.dataset.field=f.name; input.dataset.definition=key; input.placeholder=placeholder;
        input.setAttribute("aria-label",f.name+" "+key.replaceAll("_"," ")); cells.push(input);
      }); return cells;
    })));
    $("data-upload-fields").hidden = false; $("data-error").hidden = true;
  } catch(error) { if (revision === uploadRevision) dataFailure(error); }
}
function dataImportPayload() {
  if (!dataUpload) throw new Error("Choose a structured file first.");
  const metadata = {};
  const ids = {id:"data-id",name:"data-name",record_type:"data-type",objective:"data-objective",data_kind:"data-kind",version:"data-version",available_date:"data-available",source_url:"data-source-url"};
  Object.entries(ids).forEach(([key,id]) => metadata[key] = $(id).value.trim());
  const definitions=Object.create(null);
  document.querySelectorAll("#data-dictionary input").forEach(input => { if (input.value.trim()) { definitions[input.dataset.field] ||= {}; definitions[input.dataset.field][input.dataset.definition]=input.value.trim(); } });
  metadata.field_definitions=definitions;
  const mapping = {}; ["id","text","entities","effective_date","available_date","source_url"].forEach(key => mapping[key] = $("data-map-"+key).value);
  return {...dataUpload,metadata,mapping};
}
async function previewDataImport(event) {
  event.preventDefault(); $("data-preview-button").disabled = true; invalidateImport();
  const revision=importFormRevision;
  try {
    const payload=dataImportPayload(), result=await api("/api/data/preview",payload);
    if (revision !== importFormRevision) return; reviewedImport={...payload,preview_digest:result.preview_digest};
    const target=$("data-preview"); target.replaceChildren(node("h3","Import preview"),node("p",number(result.records)+" records · "+number(result.entity_links)+" entity links · "+result.new_external_entities.length+" new external entities","context-copy"),table(["Field","Type"],result.fields.map(f => [f.name,f.type])));
    if (!result.entity_links) target.append(node("p","No existing entities are linked. Records will still connect to their dataset and source.","hint"));
    if (result.new_external_entities.length) target.append(node("p","New entity IDs: "+result.new_external_entities.join(", "),"hint"));
    if (result.undefined_fields.length) target.append(node("p","No declared meaning for: "+result.undefined_fields.join(", ")+". The agent must not assume units or code meanings.","hint"));
    target.append(disclosure("Inspect sample records",node("pre",JSON.stringify(result.sample,null,2),"raw-fact")),disclosure("Proposed graph links",table(["From","Relationship","To"],result.graph_preview.map(e => [e.src,e.relation,e.dst]))),node("p",result.note,"hint"));
    target.hidden=false; $("data-commit").hidden=false; $("data-commit").disabled=!importsAllowed || result.already_imported;
    $("data-commit").textContent=!importsAllowed ? "Run privately to save this import" : result.already_imported ? "Already imported" : "Import into graph"; $("data-error").hidden=true;
  } catch(error) { dataFailure(error); } finally { $("data-preview-button").disabled=false; }
}
async function commitDataImport() {
  if (!reviewedImport || !importsAllowed) return; $("data-commit").disabled=true; $("data-import-result").textContent="Importing…";
  $("data-import-form").querySelectorAll("input,select,textarea,button").forEach(control => control.disabled=true);
  try {
    const result=await api("/api/data/import",reviewedImport);
    $("data-import-result").textContent=result.status === "already imported" ? "This version was already imported." : number(result.records)+" records indexed and "+number(result.entity_links)+" entity links added. Available to the agent now.";
    reviewedImport=null; await loadDataWorkbench(); await inspectDataGraph(result.graph_node);
  } catch(error) { $("data-import-result").textContent=""; dataFailure(error); $("data-commit").disabled=!reviewedImport; }
  finally { $("data-import-form").querySelectorAll("input,select,textarea,button").forEach(control => control.disabled=false); }
}
async function inspectDataGraph(entity) {
  $("data-graph-entity").value=entity; const result=await api("/api/data/graph?entity="+encodeURIComponent(entity)), target=$("data-graph"); target.replaceChildren();
  if (!result.edges.length) { target.append(node("p","No links found for this entity.","hint")); return; }
  const nodeButton = (id,edge) => id.startsWith("source:") ? link(edge.source_uri || edge.source_url || id,edge.source_uri || edge.source_url) : button(id,() => inspectDataGraph(id).catch(dataFailure),"source-button");
  const rows=result.edges.map(edge => {
    const evidence=edge.source_kind === "imported" ? button("View record",async () => {
      try { const data=await api("/api/evidence/"+[edge.dataset_id,edge.version,edge.record_id].map(encodeURIComponent).join("/")); dataDetail(edge.record_id,node("pre",JSON.stringify(data,null,2),"raw-fact")); }
      catch(error) { dataFailure(error); }
    }) : edge.path ? edge.path+(edge.line ? " · "+edge.line : "") : edge.source_id || "";
    return [nodeButton(edge.src,edge),edge.relation,nodeButton(edge.dst,edge),evidence];
  });
  target.append(table(["From","Relationship","To","Evidence"],rows));
  if (result.limited) target.append(node("p","Showing the first 100 links. Select a record to narrow the view.","hint"));
}
function openCalculation(line, result) {
  $("calculation-title").textContent = line.scope_item_id + " · " + line.description;
  const content = $("calculation-content"); content.replaceChildren();
  content.append(node("p","ASSUMED QUANTITY","eyebrow"),node("h3",line.quantity_basis.formula+" = "+number(line.quantity)+" "+line.unit),node("p",line.quantity_basis.note,"hint"));
  content.append(node("p","Inputs: "+number(result.inputs.disturbed_area_m2)+" m² disturbed · "+result.inputs.depth_m+" m depth · "+number(result.inputs.rock_fraction*100)+"% rock · spoil "+result.inputs.spoil_haul_km+" km · fill "+result.inputs.fill_haul_km+" km · depot "+result.inputs.mobilisation_km+" km.","hint"));
  content.append(node("div",number(line.quantity)+" × "+fmt(line.rate_central_cents,2)+" = "+fmt(line.central_cents,2)+" ex GST","calculation-total"),node("p",line.aggregation.method,"hint"));
  content.append(table(["Quoted source","Original unit rate","Adjustment","Adjusted unit rate","Role"],line.rate_evidence.map(e => {
    const src = node("div"); src.append(sourceButton(e.quote_id,e.evidence.line,e.quote_id+" · line "+e.evidence.line),node("small",e.vendor_name,"cell-note"));
    const delta = node("div"); delta.append(node("span",signedMoney(e.adjustment_cents)));
    e.adjustments.forEach(a => delta.append(node("small",a.coefficient_cents === undefined ? a.reason : a.reason+": ("+a.target_km+" − "+a.source_km+") km × "+fmt(a.coefficient_cents,2)+" "+a.coefficient_unit,"cell-note")));
    return [src,fmt(e.quoted_rate_cents,2),delta,fmt(e.adjusted_rate_cents,2),e.roles.join(" / ") || "Supporting rate"];
  })));
  const hashes = node("div"); line.rate_evidence.forEach(e => hashes.append(node("p",e.quote_id+" · SHA-256 "+e.document_sha256,"hash")));
  content.append(node("p","Source buttons open the original numbered bid line. Quoted rates, quantities and suppliers are synthetic; haul coefficients are invented. The median combines supporting offers, not a supplier commitment.","notice"),disclosure("Document integrity hashes",hashes));
  $("calculation").showModal();
}
async function boot() {
  try {
    const status = await api("/api/status");
    workspaceUnlocked = true; modelReady = status.llm_ready;
    importsAllowed = status.imports_allowed !== false;
    $("data-readonly").hidden = importsAllowed;
    $("access").hidden = true; $("workspace").hidden = !simulationOpen; $("access-error").hidden = true;
    if (status.public_demo) { accessToken=""; sessionStorage.removeItem("earthworks-access"); }
    else sessionStorage.setItem("earthworks-access",accessToken);
    $("access-token").value = "";
    $("status").replaceChildren(node("strong",number(status.counts.quotes)+" quotes / "+status.counts.projects+" jobs / "+status.counts.vendors+" suppliers"),node("div",status.backend === "postgres-pgvector" ? "PostgreSQL + pgvector" : "SQLite offline development mode"),node("div",number(status.counts.context_edges)+" bid links + "+number(status.public_context_counts.public_context_edges)+" public-context links"),node("div",status.llm_enabled ? "Live conversational agent · usage capped" : "Scripted tools · paid API disabled"));
    $("agent-availability").textContent = status.budget?.exhausted ? "The shared live-chat allowance has been used. You can still explore the bids, evidence and data model." : modelReady ? "" : "Live chat is currently offline. You can still explore the bids, evidence and data model.";
    updateConversationControls();
    const projects = await api("/api/projects"); clear("project");
    const placeholder = node("option","Select a reference job…"); placeholder.value = ""; $("project").append(placeholder);
    projects.forEach(p => { const option = node("option",p.id+" · "+p.name+" · "+p.tender_date); option.value = p.id; $("project").append(option); });
    renderProjectPanels();
    await loadProject();
  } catch (error) { if (error.status !== 401) fail(error); }
}
function conversationBubble(role, text) {
  const bubble = node("div",undefined,"conversation-bubble "+role);
  bubble.append(node("p",role === "user" ? "YOUR BRIEF" : "EARTHWORKS AGENT","eyebrow"),node("p",text,"bubble-text"));
  $("conversation-messages").append(bubble); return bubble;
}
function savedConversation() {
  pendingSavedSimulation = null; $("saved-simulation").hidden = true;
  try { sessionStorage.setItem("earthworks-conversation",JSON.stringify({simulationId,brief:conversationBrief,history:conversationHistory.slice(-6),workingEstimate,sourceMemory,latestCalculations,lastConversation,packagePlan,evidenceLog,evidenceSources,asOf:$("agent-asof").value})); } catch { /* Browser storage is optional. */ }
}
function humanise(value) { return String(value).replaceAll("_"," ").replace(/^./,c => c.toUpperCase()); }
function projectFacts() {
  const facts = node("dl",undefined,"brief-facts");
  const labels = {suburb:"Location",planned_start_date:"Work starts",disturbed_area_m2:"Disturbed area, m²",site_area_acres:"Property area, acres",depth_m:"Excavation depth, m",rock_fraction:"Rock fraction",spoil_haul_km:"Disposal haul, km",fill_haul_km:"Fill delivery, km",mobilisation_km:"Mobilisation, km"};
  Object.entries(labels).forEach(([key,label]) => { if (conversationBrief[key] != null) facts.append(node("dt",label),node("dd",String(conversationBrief[key]))); });
  (conversationBrief.facts || []).forEach(f => facts.append(node("dt",f.label),node("dd",f.value+" · "+f.basis)));
  return facts;
}
function collectProjectEvidence(result) {
  const sources = [...(result.citations || []),...(result.evidence_steps || []).flatMap(step => step.sources || [])];
  const book = new Map(evidenceSources.map(s => [s.id,s])); sources.forEach(s => { book.delete(s.id); book.set(s.id,s); }); evidenceSources = [...book.values()].slice(-60);
  let steps = result.evidence_steps || [];
  if (!steps.length && result.analysis && !result.analysis.estimate && !result.analysis.calculations && !result.analysis.plan) {
    const data = result.analysis.web_lookup || result.analysis;
    steps = [{tool:"Retrieved evidence",arguments:{query:data.query},result:data,sources:result.citations || []}];
  }
  steps.filter(step => !["calculate_quantities","estimate_costs","analyse_earthworks_brief"].includes(step.tool)).forEach(step => {
    const key = step.tool+JSON.stringify(step.arguments), entry = {...step,key,recordedAt:new Date().toISOString()};
    evidenceLog = [...evidenceLog.filter(old => old.key !== key),entry].slice(-24);
  });
  if (result.package_plan) packagePlan = result.package_plan;
  else if (result.analysis?.plan) packagePlan = result.analysis.plan;
  if (result.estimate_updated) packagePlan = null;
}
function renderProjectPanels() {
  renderLiveCalculation(); renderLiveContext();
}
function renderLiveCalculation() {
  const target = $("calculation-results"); target.replaceChildren();
  if (workingEstimate) {
    target.append(node("div",fmt(workingEstimate.low_cents)+" — "+fmt(workingEstimate.high_cents),"range-number"),node("p",workingEstimate.title+" · AUD ex GST","hint"));
    target.append(table(["Item","Quantity","Unit rate","Amount"],workingEstimate.lines.map(line => [
      button(line.description,() => openComponent(line),"source-button"),
      number(line.quantity_low)+"–"+number(line.quantity_high)+" "+line.unit,
      fmt(line.rate_low_cents,2)+"–"+fmt(line.rate_high_cents,2),fmt(line.low_cents)+"–"+fmt(line.high_cents)])));
    target.append(node("p",humanise(workingEstimate.confidence)+" input confidence: "+workingEstimate.confidence_reason,"hint"));
    workingEstimate.unpriced_items.forEach(item => target.append(node("p","Unpriced: "+item,"unpriced-note")));
  } else if (packagePlan?.reference_estimate) {
    const estimate = packagePlan.reference_estimate;
    target.append(node("div",fmt(packagePlan.low_cents)+" — "+fmt(packagePlan.high_cents),"range-number"),node("p",packagePlan.range_basis || estimate.range_basis,"hint"));
    if (packagePlan.reference_uses_midpoint_assumptions) target.append(node("p","The breakdown below uses midpoint assumptions for unanswered questions.","hint"));
    target.append(table(["Item","Quantity","Unit rate","Amount"],estimate.breakdown.map(line => [button(line.description,() => openCalculation(line,estimate),"source-button"),number(line.quantity)+" "+line.unit,fmt(line.rate_central_cents,2),fmt(line.central_cents,2)])));
    (packagePlan.questions || []).forEach(q => target.append(node("p",q.question,"followup")));
  }
  if (latestCalculations.length) {
    const calculations = node("div",undefined,"live-calculations");
    latestCalculations.forEach(c => {
      const card = node("article",undefined,"live-evidence-card");
      card.append(node("h3",c.label),node("div",number(c.value)+" "+c.unit,"quantity-result"),node("p",c.expression,"calculation-expression"));
      if (c.assumption) card.append(node("p",c.assumption,"hint")); calculations.append(card);
    }); target.append(calculations);
  }
  if (!target.childNodes.length) target.append(node("p","No calculations yet. Quantities and prices will appear as the agent calculates them.","hint"));
}
function openComponent(line) {
  $("calculation-title").textContent = line.description;
  const content = $("calculation-content"); content.replaceChildren();
  content.append(node("p",number(line.quantity_low)+"–"+number(line.quantity_high)+" "+line.unit+" × "+fmt(line.rate_low_cents,2)+"–"+fmt(line.rate_high_cents,2),"calculation-expression"),node("div",fmt(line.low_cents)+" — "+fmt(line.high_cents)+" ex GST","calculation-total"),node("p",line.assumption,"hint"));
  const refs = [line.low_basis,line.high_basis].filter(ref => ref !== "assumption");
  const sources = evidenceSources.filter(source => refs.includes(source.id));
  if (sources.length) content.append(citationLinks(sources));
  if (line.low_basis === "assumption" || line.high_basis === "assumption") content.append(node("p","Includes a provisional model rate allowance.","hint"));
  $("calculation").showModal();
}
function renderLiveContext() {
  const target = $("project-context"); target.replaceChildren();
  const facts = projectFacts();
  if (facts.childNodes.length || conversationBrief.scope_note) {
    const section = node("section",undefined,"live-context-section"); section.append(node("h3","Known so far"),facts);
    if (conversationBrief.scope_note) section.append(node("p",conversationBrief.scope_note,"hint")); target.append(section);
  }
  if (evidenceLog.length) {
    const section = node("section",undefined,"live-context-section"); section.append(node("h3","Evidence gathered"));
    [...evidenceLog].reverse().forEach(step => {
      const data = step.result, detail = data.evidence || data.web_lookup || data;
      const card = node("article",undefined,"live-evidence-card"), args = step.arguments || {};
      card.append(node("h3",args.query || humanise(args.topic || step.tool)),node("p",[args.suburb,args.location,step.recordedAt?.slice(0,10)].filter(Boolean).join(" · "),"hint"));
      const summary = detail.answer || detail.message || detail.status || (Array.isArray(data.quotes) ? data.quotes.length+" source quotation(s) retrieved." : Array.isArray(data.matches) ? data.matches.length+" evidence record(s) retrieved." : null);
      if (summary) card.append(node("p",String(summary).replace(/[^]*/g,""),"context-copy"));
      if (step.sources?.length) card.append(citationLinks(step.sources));
      card.append(disclosure("Evidence details",node("pre",JSON.stringify(data,null,2),"raw-fact"))); section.append(card);
    }); target.append(section);
  }
  if (evidenceSources.length) {
    const section = node("section",undefined,"live-context-section"); section.append(node("h3","Sources consulted"),citationLinks(evidenceSources)); target.append(section);
  }
  if (!target.childNodes.length) target.append(node("p","Context will appear as you discuss the job. Nothing has been assumed or looked up yet.","hint"));
}
function renderBidCards(quotes) {
  clear("bids");
  if (!quotes.length) { $("bids").append(node("p","No bids retrieved yet. Discuss the job or select a reference job.","hint")); return; }
  quotes.forEach(q => {
    const card = node("article",undefined,"bid");
    card.append(node("span",q.id+(q.project_id ? " · "+q.project_id : ""),"quote-id"),node("h3",q.vendor_name),node("div",fmt(q.contract_ex_gst_cents),"bid-price"),node("p","Synthetic reference quotation · ex GST","hint"));
    const terms = node("dl");
    [["Priced options",fmt(q.optional_ex_gst_cents)],["Deposit",q.deposit_percent+"% / "+fmt(q.deposit_cents)]].forEach(([label,value]) => terms.append(node("dt",label),node("dd",value)));
    card.append(terms);
    if (q.findings?.length) card.append(node("p",q.findings.map(f => humanise(f.kind)+": "+f.item).join(" · "),"flag"));
    card.append(sourceButton(q.id,1,"Inspect source bid ↗")); $("bids").append(card);
  });
}
async function loadReferenceBids() {
  const revision = projectRevision;
  const ids = [...new Set(evidenceSources.filter(s => s.kind === "quote").map(s => s.quote_id))].slice(-12);
  const results = await Promise.allSettled(ids.filter(id => !referenceBids[id]).map(async id => { const quote = await api("/api/quote/"+encodeURIComponent(id)); if (revision === projectRevision) referenceBids[id] = quote; }));
  if (selectedProject || revision !== projectRevision) return;
  const current = [...new Set(evidenceSources.filter(s => s.kind === "quote").map(s => s.quote_id))].slice(-12);
  $("project-meta").textContent = current.length ? "Quotations retrieved during this conversation. Check scope before comparing." : "";
  renderBidCards(current.filter(id => referenceBids[id]).map(id => referenceBids[id]));
  if (results.some(result => result.status === "rejected")) $("project-meta").textContent = "Some source quotations could not be loaded.";
}
async function loadProject() {
  selectedProject = $("project").value || null;
  if (!selectedProject) return loadReferenceBids();
  try {
    const pack = await api("/api/project/"+encodeURIComponent(selectedProject)), p = pack.project;
    if ($("project").value !== p.id) return;
    $("project-meta").textContent = p.name+" · "+p.site_address+" · "+number(p.disturbed_area_m2)+" m² disturbed · "+p.tender_date;
    renderBidCards(pack.quotes);
  } catch (error) { fail(error); }
}
function citationLinks(citations) {
  const sources = node("div",undefined,"source-links answer-sources");
  citations.forEach(c => sources.append(c.kind === "quote" ? sourceButton(c.quote_id,c.line,c.title || c.id) : c.kind === "dataset" ? button(c.title || c.id,async () => {
    try {
      const record = await api("/api/evidence/"+[c.dataset_id,c.version,c.record_id].map(encodeURIComponent).join("/"));
      $("document-title").textContent = c.title+" · version "+c.version;
      $("document-text").textContent = JSON.stringify(record,null,2); $("document").showModal();
    } catch (error) { fail(error); }
  },"source-button") : link(c.title || c.id,c.url)));
  return sources;
}
function answerProvenance(bubble, result) {
  const content = node("div");
  (result.provenance || ["Reasoned from the current brief."]).slice(0,3).forEach(line => content.append(node("p",line,"hint")));
  if (result.citations?.length) content.append(citationLinks(result.citations));
  bubble.append(disclosure("How I got this",content));
}
function estimateScopeSummary(priced, unpriced) {
  const summary = node("dl",undefined,"estimate-scope-summary"); summary.setAttribute("aria-label","Estimate coverage");
  [["Priced",priced],["Unpriced",unpriced]].forEach(([label,items]) => {
    const names = [...new Set((items || []).filter(item => typeof item === "string" && item.trim()))];
    const group = node("div",undefined,label.toLowerCase()), description = node("dd");
    group.append(node("dt",label+(names.length ? " · "+names.length : "")));
    description.append(node("span",names.slice(0,3).join("; ") || "None listed"));
    if (names.length > 3) {
      const rest = node("ul"); names.slice(3).forEach(name => rest.append(node("li",name)));
      description.append(disclosure("+"+(names.length-3)+" more",rest));
    }
    group.append(description); summary.append(group);
  });
  return summary;
}
function renderConversationEvidence(result) {
  const target = $("conversation-evidence"), analysis = result.analysis || {}, plan = packagePlan || analysis.plan || {}, reference = plan.reference_estimate;
  target.replaceChildren();
  if (result.working_estimate) workingEstimate = result.working_estimate;
  if (result.estimate_updated) latestCalculations = [];
  if (result.calculations?.length) {
    const cache = new Map(latestCalculations.map(c => [c.label,c]));
    result.calculations.forEach(c => cache.set(c.label,c)); latestCalculations = [...cache.values()].slice(-8);
  }
  if (workingEstimate) {
    target.append(node("div",fmt(workingEstimate.low_cents)+" — "+fmt(workingEstimate.high_cents),"conversation-range"),node("p",workingEstimate.title+" · AUD ex GST","hint"));
    target.append(estimateScopeSummary(workingEstimate.lines.map(line => line.description),workingEstimate.unpriced_items));
    const badge = node("div",undefined,"confidence-badge "+workingEstimate.confidence);
    badge.append(node("span","Input confidence"),node("strong",workingEstimate.confidence[0].toUpperCase()+workingEstimate.confidence.slice(1))); target.append(badge);
    const details = node("div"); details.append(node("p",workingEstimate.confidence_reason,"hint"));
    details.append(table(["Item","Quantity range","Rate range","Cost range"],workingEstimate.lines.map(line => [line.description,number(line.quantity_low)+"–"+number(line.quantity_high)+" "+line.unit,fmt(line.rate_low_cents,2)+"–"+fmt(line.rate_high_cents,2),fmt(line.low_cents)+"–"+fmt(line.high_cents)])));
    workingEstimate.lines.forEach(line => details.append(node("p",line.description+": "+line.assumption+(line.low_basis === "assumption" || line.high_basis === "assumption" ? " · Model allowance" : " · Quoted source rates"),"hint")));
    workingEstimate.unpriced_items.forEach(text => details.append(node("p","Unpriced: "+text,"hint")));
    target.append(disclosure("Estimate details",details));
  } else if (plan.low_cents !== undefined) {
    target.append(node("div",fmt(plan.low_cents)+" — "+fmt(plan.high_cents),"conversation-range"),node("p","AUD ex GST · scenario range","hint"));
    target.append(estimateScopeSummary((reference?.breakdown || []).map(line => line.description),plan.unpriced_conditions));
  } else target.append(node("div","—","conversation-range"),node("p","Input confidence · awaiting details","hint"));
  const volumes = latestCalculations.filter(c => /m[³3]|cubic/i.test(c.unit)).slice(-2);
  volumes.forEach(c => target.append(node("p",c.label+": "+number(c.value)+" "+c.unit,"volume-summary")));
  const facts = node("dl",undefined,"brief-facts");
  const labels = {disturbed_area_m2:"Disturbed area, m²",site_area_acres:"Property area, acres",depth_m:"Excavation depth, m",rock_fraction:"Rock fraction",spoil_haul_km:"Disposal haul, km",fill_haul_km:"Fill delivery, km",mobilisation_km:"Mobilisation, km",suburb:"Regional location",planned_start_date:"Work starts"};
  Object.entries(labels).forEach(([key,label]) => { if (result.brief[key] != null) facts.append(node("dt",label),node("dd",String(result.brief[key]))); });
  (result.brief.facts || []).forEach(fact => facts.append(node("dt",fact.label),node("dd",fact.value+" · "+fact.basis)));
  const inputsDetail = node("div"); inputsDetail.append(facts);
  if (result.brief.scope_note) inputsDetail.append(node("p",result.brief.scope_note,"hint"));
  (analysis.assumed_defaults || []).forEach(text => inputsDetail.append(node("p",text,"hint")));
  if (latestCalculations.length) latestCalculations.forEach(c => inputsDetail.append(node("p",c.label+": "+c.expression+" = "+number(c.value)+" "+c.unit+". "+c.assumption,"hint")));
  if (facts.childNodes.length || result.brief.scope_note) target.append(disclosure("Project inputs",inputsDetail));
  if (reference) {
    target.append(button("Inspect calculation & sources ↗",() => showPanel("estimate")));
    const largest = [...reference.breakdown].sort((a,b) => b.central_cents-a.central_cents)[0];
    target.append(button(plan.questions.length ? "Explain the largest midpoint cost item" : "Explain the largest cost item",() => openCalculation(largest,reference)));
  }
}
async function converse(event) {
  event.preventDefault(); const draft = $("job-message").value, message = draft.trim();
  if (!message || sendingMessage || !workspaceUnlocked || !modelReady) return;
  sendingMessage = true; updateConversationControls(); $("conversation-error").hidden = true;
  const submitted = conversationBubble("user",message), waiting = conversationBubble("assistant","Thinking about your message…");
  waiting.classList.add("is-thinking"); waiting.setAttribute("role","status");
  const spinner = node("span",undefined,"thinking-spinner"); spinner.setAttribute("aria-hidden","true");
  waiting.querySelector(".bubble-text").prepend(spinner);
  $("job-message").value = "";
  try {
    let history = conversationHistory.slice(-4).map(item => ({role:item.role,content:item.content.slice(0,850)}));
    while (history.length && new TextEncoder().encode(JSON.stringify(history)+message).length > 4400) history.shift();
    const rememberedSources = [...new Map([...evidenceSources,...sourceMemory].map(source => [source.id,source])).values()].slice(-32);
    const result = await api("/api/converse",{message,brief:conversationBrief,history,as_of:$("agent-asof").value,estimate_inputs:workingEstimate?.inputs || null,source_memory:rememberedSources});
    waiting.remove(); conversationBrief = result.brief; lastConversation = result;
    const bubble = conversationBubble("assistant",result.explanation);
    result.questions.forEach(q => bubble.append(node("p",q,"followup")));
    answerProvenance(bubble,result); sourceMemory = result.source_memory || sourceMemory;
    conversationHistory.push({role:"user",content:message},{role:"assistant",content:result.explanation+"\n"+result.questions.join("\n"),provenance:result.provenance,citations:result.citations});
    collectProjectEvidence(result); renderConversationEvidence(result); renderProjectPanels(); savedConversation();
    loadReferenceBids().catch(() => { /* A source-card failure must not fail a sent message. */ });
    bubble.scrollIntoView({block:"nearest",behavior:"smooth"});
  } catch (error) {
    waiting.remove(); submitted.remove();
    $("job-message").value = draft;
    if (error.status !== 401) {
      if (error.code === "DEMO_SPEND_LIMIT") { modelReady=false; $("agent-availability").textContent="The shared live-chat allowance has been used. You can still explore the bids, evidence and data model."; }
      const messages = {DEMO_SPEND_LIMIT:"The demo’s usage allowance has been reached. Your project and draft are saved.",PROVIDER_RATE_LIMIT:"The AI service is temporarily rate-limited. Your project and draft are saved; please try again shortly.",MODEL_UNAVAILABLE:"Chat is currently unavailable. Your project and draft are saved. The server’s model settings need checking."};
      $("conversation-error").textContent = messages[error.code] || "I couldn’t complete that reply. Your project is saved and your draft has been restored. Please try again."; $("conversation-error").hidden = false;
    }
  }
  finally { sendingMessage = false; updateConversationControls(); }
}
const localToday = new Date(); $("agent-asof").value = new Date(localToday.getTime()-localToday.getTimezoneOffset()*60000).toISOString().slice(0,10);
function resumeSimulation() {
  const saved = pendingSavedSimulation;
  if (!saved || sendingMessage) return;
  resetSimulation(false); simulationId = saved.simulationId || crypto.randomUUID();
  conversationBrief = saved.brief || {}; conversationHistory = saved.history || []; workingEstimate = saved.workingEstimate || null;
  sourceMemory = saved.sourceMemory || []; latestCalculations = saved.latestCalculations || []; lastConversation = saved.lastConversation;
  packagePlan = saved.packagePlan || null; evidenceLog = saved.evidenceLog || []; evidenceSources = saved.evidenceSources || [];
  if (saved.asOf) $("agent-asof").value = saved.asOf;
  conversationHistory.forEach(item => { const bubble = conversationBubble(item.role,item.content); if (item.role === "assistant") answerProvenance(bubble,item); });
  if (lastConversation) {
    if (!saved.evidenceLog) {
      evidenceSources = [...new Map([...conversationHistory.flatMap(item => item.citations || []),...sourceMemory].map(source => [source.id,source])).values()];
      collectProjectEvidence(lastConversation);
    }
    renderConversationEvidence(lastConversation);
  }
  renderProjectPanels(); savedConversation(); loadReferenceBids().catch(fail);
}
try {
  const saved = JSON.parse(sessionStorage.getItem("earthworks-conversation") || "{}");
  if (saved.history?.length || saved.lastConversation || saved.workingEstimate) { pendingSavedSimulation = saved; $("saved-simulation").hidden = false; }
} catch { /* Optional local conversation draft. */ }
renderProjectPanels();
document.querySelectorAll(".tab").forEach(b => b.addEventListener("click",() => showPanel(b.dataset.panel)));
$("data-refresh").addEventListener("click",() => loadDataWorkbench().catch(dataFailure));
$("data-file").addEventListener("change",readDataFile);
$("data-import-form").addEventListener("input",invalidateImport);
$("data-import-form").addEventListener("change",invalidateImport);
$("data-import-form").addEventListener("submit",previewDataImport);
$("data-commit").addEventListener("click",commitDataImport);
$("data-graph-form").addEventListener("submit",event => { event.preventDefault(); inspectDataGraph($("data-graph-entity").value.trim()).catch(dataFailure); });
$("close-data-detail").addEventListener("click",() => $("data-detail").close());
$("project").addEventListener("change",loadProject);
$("access-form").addEventListener("submit",async event => { event.preventDefault(); accessToken = $("access-token").value.trim(); $("unlock").disabled = true; try { await boot(); } finally { $("unlock").disabled = false; } });
$("close-document").addEventListener("click",() => $("document").close());
$("close-calculation").addEventListener("click",() => $("calculation").close());
$("conversation-form").addEventListener("submit",converse);
$("example-brief").addEventListener("click",() => { $("job-message").value = "I help run a school in South Brisbane. We'd like to level a grassy slope for a play area, roughly 40 m by 10 m. I don't have a survey. Can you give me a rough budget?"; $("job-message").focus(); });
function resetSimulation(persist = true) {
  conversationBrief = {}; conversationHistory = []; lastConversation = null; workingEstimate = null; sourceMemory = []; latestCalculations = [];
  packagePlan = null; evidenceLog = []; evidenceSources = []; referenceBids = {}; selectedProject = null; $("project").value = ""; $("project-meta").textContent = "";
  projectRevision++; simulationId = crypto.randomUUID(); pendingSavedSimulation = null; $("saved-simulation").hidden = true;
  clear("conversation-messages"); $("conversation-evidence").replaceChildren(node("div","—","conversation-range"),node("p","Input confidence · awaiting details","hint"));
  $("job-message").value = ""; $("conversation-error").hidden = true; renderProjectPanels(); renderBidCards([]); showPanel("conversation");
  if (persist) savedConversation();
}
$("reset-conversation").addEventListener("click",() => resetSimulation());
$("resume-simulation").addEventListener("click",resumeSimulation);
$("discard-simulation").addEventListener("click",() => resetSimulation());
$("start-simulation").addEventListener("click",async () => {
  $("start-simulation").disabled=true;
  try { await initialBoot; simulationOpen=true; $("intro").hidden=true; $("about-poc").hidden=false; $("workspace").hidden=!workspaceUnlocked; $("access").hidden=workspaceUnlocked; }
  finally { $("start-simulation").disabled=false; }
});
$("about-poc").addEventListener("click",() => { simulationOpen=false; $("intro").hidden=false; $("workspace").hidden=true; $("access").hidden=true; $("about-poc").hidden=true; $("start-simulation").textContent=conversationHistory.length ? "Continue the simulation ↗" : "Try the simulation ↗"; });
$("job-message").addEventListener("keydown",event => { if (event.key === "Enter" && !event.shiftKey && !event.isComposing && !$("send-brief").disabled) { event.preventDefault(); $("conversation-form").requestSubmit(); } });

const initialBoot = boot();

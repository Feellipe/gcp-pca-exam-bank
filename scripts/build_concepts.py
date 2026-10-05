"""Build the concept layer for the exam bank.

Concept LINKAGE comes from the written slide text (stem + option lines), never
from the transcript: the presenter rarely names a product while explaining
(Dataflow is on 17 slides but spoken in 4), and the ASR mangles acronyms
(IAM -> "IM", microservice -> "micros service"). The transcript is used only to
carry the teaching prose on each concept page, clearly flagged as ASR-derived.

Writes `concepts` + `question_concepts` into exam.db and exports work/concepts.json
so the wiki pages can be generated without touching the DB again.

Usage:
    python scripts/build_concepts.py [--db exam/exam.db] [--out work/concepts.json]
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from pathlib import Path

# (canonical, category, [aliases]).  Ambiguous bare words (monitoring, logging,
# NAT, CDN, DNS, tasks) are deliberately NOT aliases - they match ordinary prose
# like "monitoring agents" and would create false links. Only product-qualified
# forms are used, which is why the canonical names are spelled out in full.
GLOSSARY: list[tuple[str, str, list[str]]] = [
    # --- compute -------------------------------------------------------------
    ("Compute Engine", "compute", ["Google Compute Engine", "GCE", "Compute Engine VM"]),
    ("Google Kubernetes Engine", "compute", ["GKE", "Kubernetes Engine"]),
    ("Kubernetes", "compute", ["K8s"]),
    ("Cloud Run", "compute", ["CloudRun", "Cloud Run for Anthos", "Cloud Run functions"]),
    ("Cloud Functions", "compute", ["Cloud Function", "Google Cloud Functions"]),
    ("App Engine", "compute", ["AppEngine", "Google App Engine", "GAE"]),
    ("Managed Instance Group", "compute", ["MIG", "MIGs", "managed instance groups",
                                           "unmanaged instance group"]),
    ("Instance Template", "compute", ["instance templates", "instance group template"]),
    ("Preemptible VM", "compute", ["preemptible", "preemptible instances", "Spot VM", "spot VMs"]),
    ("Custom Machine Type", "compute", ["custom machine types"]),
    ("Shielded VM", "compute", ["Shielded VMs"]),
    ("Sole-Tenant Node", "compute", ["sole tenancy", "sole-tenant"]),
    ("Local SSD", "compute", ["local SSDs"]),
    ("Bare Metal Solution", "compute", ["Bare Metal"]),
    ("Batch", "compute", ["Google Batch"]),
    # --- storage -------------------------------------------------------------
    ("Cloud Storage", "storage", ["GCS", "Google Cloud Storage", "Cloud Storage bucket",
                                  "Cloud Storage buckets", "cloud storage"]),
    ("Cloud Storage Class", "storage", ["Standard storage class", "Nearline", "Coldline",
                                        "Archive storage", "Autoclass"]),
    ("Object Lifecycle Management", "storage", ["lifecycle policy", "lifecycle policies",
                                                "Object Lifecycle"]),
    ("Persistent Disk", "storage", ["Google Persistent Disk", "persistent disks", "PD"]),
    ("Filestore", "storage", ["Cloud Filestore"]),
    ("Storage Transfer Service", "storage", ["Storage Transfer"]),
    ("Transfer Appliance", "storage", []),
    ("Snapshot", "storage", ["snapshots", "snapshot schedule"]),
    # --- database ------------------------------------------------------------
    ("Cloud SQL", "database", ["CloudSQL", "Google Cloud SQL"]),
    ("Cloud Spanner", "database", ["Spanner", "CloudSpanner"]),
    ("Cloud Bigtable", "database", ["Bigtable", "BigTable"]),
    ("Firestore", "database", ["Cloud Firestore"]),
    ("Datastore", "database", ["Cloud Datastore", "Data Store"]),
    ("Memorystore", "database", ["Cloud Memorystore", "Memorystore for Redis"]),
    ("AlloyDB", "database", ["AlloyDB for PostgreSQL"]),
    # --- data / analytics ----------------------------------------------------
    ("BigQuery", "data", ["Big Query", "BigQuery ML", "BigQuery slot", "BigQuery reservation",
                          "BigQuery Reservations", "BQ"]),
    ("Dataflow", "data", ["Cloud Dataflow", "Data Flow", "Apache Beam"]),
    ("Dataproc", "data", ["Cloud Dataproc", "Apache Spark", "Apache Hadoop", "Hadoop"]),
    ("Pub/Sub", "data", ["PubSub", "Pub Sub", "Cloud Pub/Sub"]),
    ("Data Fusion", "data", ["Cloud Data Fusion"]),
    ("Datastream", "data", ["Cloud Datastream"]),
    ("Cloud Composer", "data", ["Cloud Composer", "Apache Airflow", "Airflow"]),
    ("Dataprep", "data", ["Cloud Dataprep"]),
    ("Looker", "data", ["Looker Studio", "Google Looker"]),
    ("Data Catalog", "data", ["Dataplex"]),
    ("Cloud Data Loss Prevention", "data", ["DLP", "Data Loss Prevention", "Cloud DLP"]),
    ("Kafka", "data", []),
    # --- AI / ML -------------------------------------------------------------
    ("Vertex AI", "ai", ["AutoML", "AI Platform", "AI Platform Pipelines", "Vertex"]),
    ("Dialogflow", "ai", ["Contact Center AI", "CCAI"]),
    ("Speech-to-Text", "ai", ["Speech to Text"]),
    ("Document AI", "ai", []),
    ("Vision AI", "ai", ["Cloud Vision"]),
    ("Gemini", "ai", ["Generative AI", "GenAI", "large language model", "LLM"]),
    # --- networking ----------------------------------------------------------
    ("VPC", "network", ["VPCs", "Virtual Private Cloud", "VPC network", "VPC networks"]),
    ("Subnet", "network", ["subnetwork", "subnets", "subnetworks"]),
    ("Firewall Rule", "network", ["firewall rules", "firewall"]),
    ("Shared VPC", "network", ["Shared VPCs", "host project", "service project"]),
    ("VPC Peering", "network", ["VPC peering", "peering"]),
    ("Cloud VPN", "network", ["CloudVPN", "Cloud VPNs", "HA VPN", "VPN"]),
    ("Cloud Interconnect", "network", ["Dedicated Interconnect", "Partner Interconnect",
                                       "Interconnect", "Cloud Interconnect"]),
    ("Cloud Router", "network", ["Cloud Routers"]),
    ("Cloud NAT", "network", ["CloudNAT"]),
    ("Cloud DNS", "network", ["CloudDNS"]),
    ("Cloud CDN", "network", ["CloudCDN"]),
    ("Cloud Load Balancing", "network", ["Load Balancer", "load balancer", "load balancers",
                                         "HTTP(S) Load Balancer", "global load balancer",
                                         "Network Load Balancer", "Internal Load Balancer"]),
    ("Private Google Access", "network", ["Private Google Access", "Private Service Connect",
                                          "Private Service Access"]),
    ("VPC Service Controls", "network", ["Service Controls", "VPC-SC", "VPC SC"]),
    ("Network Service Tier", "network", ["Premium Tier", "Standard Tier", "network tiers"]),
    ("Traffic Director", "network", ["Anthos Service Mesh", "service mesh"]),
    ("Cloud Endpoints", "network", []),
    ("Apigee", "network", ["Apigee X"]),
    ("Cloud Armor", "network", ["Cloud Armor security policy"]),
    ("Identity-Aware Proxy", "network", ["IAP", "Identity Aware Proxy", "BeyondCorp"]),
    ("Cloud IDS", "network", []),
    # --- identity / security -------------------------------------------------
    ("Cloud IAM", "security", ["IAM", "Cloud IAM", "Identity and Access Management",
                               "IAM policy", "IAM policies", "IAM role", "IAM roles",
                               "IAM permissions", "IAM binding",
                               # role names only exist as IAM bindings in these exams
                               "Project Owner", "Project Editor", "Project Viewer",
                               "Owner role", "Editor role", "Viewer role"]),
    ("Service Account", "security", ["service accounts", "Service Accounts"]),
    ("Workload Identity", "security", ["Workload Identity Federation", "workload identity"]),
    ("Cloud KMS", "security", ["KMS", "Key Management Service", "CMEK",
                               "customer-managed encryption key", "customer managed encryption"]),
    ("Secret Manager", "security", ["SecretManager", "Secrets Manager",
                                    "secret management system", "secret management"]),
    ("Cloud Identity", "security", ["Cloud Identity and Access Management", "Google Workspace"]),
    ("Resource Hierarchy", "security", ["organization node", "folders and projects",
                                        "folder hierarchy", "organization, folders, and projects"]),
    ("Organization Policy", "security", ["Org Policy", "Organizational Policy",
                                         "organization policies", "organization policy"]),
    ("Cloud Audit Logs", "security", ["Audit Logs", "audit log", "audit logs",
                                      "Admin Activity logs", "Data Access logs"]),
    ("Security Command Center", "security", ["SCC", "Cloud Security Scanner",
                                             "Web Security Scanner", "security scanner"]),
    ("Certificate Authority Service", "security", ["Certificate Authority"]),
    ("Binary Authorization", "security", ["code signing", "trusted binary repository"]),
    ("Access Transparency", "security", []),
    # --- operations / management ---------------------------------------------
    ("Cloud Monitoring", "ops", ["Stackdriver Monitoring", "Cloud Monitoring dashboards",
                                 "monitoring dashboard", "uptime check"]),
    ("Cloud Logging", "ops", ["Stackdriver Logging", "log sink", "log-based metric",
                              "Log Router", "Cloud Logging"]),
    ("Cloud Trace", "ops", ["Stackdriver Trace"]),
    ("Cloud Profiler", "ops", ["Profiler"]),
    ("Error Reporting", "ops", []),
    ("Cloud Deployment Manager", "ops", ["Deployment Manager"]),
    ("Terraform", "ops", ["terraform"]),
    ("Cloud Asset Inventory", "ops", ["Asset Inventory"]),
    ("gcloud", "ops", ["Cloud SDK", "Google Cloud SDK", "Cloud Shell", "gsutil"]),
    # --- devops / CI-CD ------------------------------------------------------
    ("Cloud Build", "devops", ["CloudBuild"]),
    ("Cloud Deploy", "devops", []),
    ("Artifact Registry", "devops", ["Container Registry", "Google Container Registry"]),
    ("Cloud Source Repositories", "devops", ["Source Repositories"]),
    ("Skaffold", "devops", []),
    ("Jenkins", "devops", []),
    ("Spinnaker", "devops", []),
    ("GitLab", "devops", ["GitHub", "Jenkins CI"]),
    # --- hybrid / multi-cloud ------------------------------------------------
    ("Anthos", "hybrid", ["Google Anthos", "Anthos Config Management", "GKE Hub",
                          "Anthos clusters", "Anthos on-prem"]),
    ("Migrate for Compute Engine", "hybrid", ["Velostrata", "Migrate for Anthos",
                                              "Migrate to Containers"]),
    ("Database Migration Service", "hybrid", ["DMS"]),
    # --- billing / cost ------------------------------------------------------
    ("Committed Use Discount", "cost", ["Committed Use Discounts", "CUD", "CUDs",
                                        "committed use"]),
    ("Sustained Use Discount", "cost", ["Sustained Use Discounts", "SUD"]),
    ("Flat-rate Pricing", "cost", ["flat rate pricing", "BigQuery flat-rate"]),
    ("Budget Alert", "cost", ["budget alerts", "Cloud Billing budget"]),
    ("Billing Export", "cost", ["billing export", "Cloud Billing export"]),
]


def build_pattern(alias: str):
    """Compile an alias into a word-boundary regex.

    Acronyms (all upper case) match case-sensitively so "IAM" cannot match
    "Miami" or "aim", and the lookarounds stop "GKE" from matching inside "GKER"
    (a real ASR artefact) or "IAP" inside "IAPs". Multi-word aliases tolerate any
    whitespace between words.
    """
    cs = alias.isupper()
    body = r"\s*".join(re.escape(w) for w in alias.split())
    flags = 0 if cs else re.IGNORECASE
    return re.compile(r"(?<![A-Za-z])" + body + r"(?![A-Za-z])", flags)


def build_glossary():
    """Return canonical -> (category, [(alias, pattern)]) with duplicates merged."""
    merged: dict[str, tuple[str, list[str]]] = {}
    for name, category, aliases in GLOSSARY:
        if name in merged:
            cat, existing = merged[name]
            existing.extend(aliases)
            continue
        merged[name] = (category, list(aliases) + [name])
    out = {}
    for name, (category, aliases) in merged.items():
        seen, pats = set(), []
        for a in aliases:
            key = a.lower()
            if key in seen:
                continue
            seen.add(key)
            pats.append((a, build_pattern(a)))
        out[name] = (category, pats)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="exam/exam.db")
    ap.add_argument("--out", default="work/concepts.json")
    args = ap.parse_args()

    gloss = build_glossary()
    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    cur.executescript("""
        DROP TABLE IF EXISTS question_concepts;
        DROP TABLE IF EXISTS concepts;
        CREATE TABLE concepts (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            name      TEXT UNIQUE NOT NULL,
            category  TEXT,
            aliases   TEXT,
            n_questions INTEGER,
            n_mentions  INTEGER
        );
        CREATE TABLE question_concepts (
            question_id   INTEGER NOT NULL REFERENCES questions(id),
            concept_id    INTEGER NOT NULL REFERENCES concepts(id),
            matched_alias TEXT,
            in_stem       INTEGER,
            in_options    INTEGER,
            PRIMARY KEY (question_id, concept_id)
        );
    """)

    rows = cur.execute(
        "SELECT id, label, number, stem, options_json, explanation, watch_url, image"
        " FROM questions"
    ).fetchall()

    per_concept: dict[str, dict] = {name: {"n_q": 0, "n_mentions": 0, "aliases": {}} for name in gloss}
    links = []
    for row in rows:
        opts = json.loads(row["options_json"] or "[]")
        stem = row["stem"] or ""
        opt_text = " ".join(o.get("text") or "" for o in opts)
        slide = stem + "\n" + opt_text
        for name, (category, pats) in gloss.items():
            hits = [(a, p) for a, p in pats if p.search(slide)]
            if not hits:
                continue
            alias = hits[0][0]
            in_stem = int(any(p.search(stem) for _, p in hits))
            in_opts = int(any(p.search(opt_text) for _, p in hits))
            links.append((row["id"], name, alias, in_stem, in_opts))
            per_concept[name]["n_q"] += 1
            per_concept[name]["n_mentions"] += len(hits)
            for a, _ in hits:
                per_concept[name]["aliases"][a] = per_concept[name]["aliases"].get(a, 0) + 1

    for name, (category, pats) in gloss.items():
        st = per_concept[name]
        cur.execute(
            "INSERT INTO concepts (name, category, aliases, n_questions, n_mentions)"
            " VALUES (?,?,?,?,?)",
            (name, category, json.dumps(sorted(st["aliases"])), st["n_q"], st["n_mentions"]),
        )
    ids = {r["name"]: r["id"] for r in cur.execute("SELECT id, name FROM concepts")}
    cur.executemany(
        "INSERT INTO question_concepts (question_id, concept_id, matched_alias, in_stem,"
        " in_options) VALUES (?,?,?,?,?)",
        [(qid, ids[name], alias, s, o) for qid, name, alias, s, o in links],
    )
    conn.commit()

    # export for the wiki generator, including the ASR-flagged transcript sentences
    qmeta = {r["id"]: r for r in rows}
    export = {"concepts": [], "drops": []}
    for name, st in sorted(per_concept.items(), key=lambda kv: -kv[1]["n_q"]):
        if st["n_q"] == 0:
            export["drops"].append(name)
            continue
        qs = []
        for qid, label, alias, in_stem, in_opts in cur.execute(
            """SELECT q.id, q.label, qc.matched_alias, qc.in_stem, qc.in_options
               FROM question_concepts qc JOIN questions q ON q.id = qc.question_id
               JOIN concepts c ON c.id = qc.concept_id
               WHERE c.name = ? ORDER BY q.number""", (name,)).fetchall():
            row = qmeta[qid]
            qs.append({
                "label": label, "number": row["number"], "alias": alias,
                "in_stem": in_stem, "in_options": in_opts,
                "watch_url": row["watch_url"], "image": row["image"],
            })
        export["concepts"].append({
            "name": name, "category": gloss[name][0], "n_questions": st["n_q"],
            "aliases": sorted(st["aliases"]), "questions": qs,
        })

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(export, indent=1), encoding="utf-8")

    print(f"# concepts with >=1 question: {len(export['concepts'])} of {len(gloss)}")
    print(f"# question-concept links: {len(links)}")
    print(f"# questions linked: {len({l[0] for l in links})} of {len(rows)}")
    print(f"# glossary entries never seen (dropped): {len(export['drops'])}"
          f" {export['drops'][:12]}")
    print(f"# exported {args.out}")
    print()
    print("top concepts:")
    for c in export["concepts"][:20]:
        print(f"   {c['n_questions']:>3}  [{c['category']:8}] {c['name']}")
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())

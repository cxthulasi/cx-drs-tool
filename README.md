

# 🚀 Coralogix DR Migration Tool

A comprehensive disaster recovery migration tool for Coralogix that helps you migrate configurations, policies, and resources between different Coralogix teams/environments.


⚠️ **NOTE (IMPORTANT) TOOL DELETES/UPDATES RESOURCES IN TEAMB**

**This tool should be used *ONLY* for Disaster Recovery (DR) scenarios — specifically to sync Team A with Team B.**

🚧 *A separate version of this tool for one-time migrations will be created later.*

A disaster recovery SYNC tool for Coralogix that helps you migrate configurations, policies, and resources between two different Coralogix teams/environments.

---

## 📋 Table of Contents

- [Overview](#overview)
- [Prerequisites](#prerequisites)
- [Installation](#installation)
- [Configuration](#configuration)
- [Quick Start](#quick-start)
- [Available Services](#available-services)
- [Usage Examples](#usage-examples)
- [Understanding Output](#understanding-output)
- [Advanced Features](#advanced-features)
- [AI Assistant](#ai-assistant)
- [Troubleshooting](#troubleshooting)
- [Best Practices](#best-practices)

---

## 🎯 **Overview**

The DR Migration Tool automates the process of migrating Coralogix configurations between teams, ensuring disaster recovery readiness and environment synchronization.

**Key Features:**

- 🧪 **Dry Run Mode** – Preview changes before execution
- 📜 **Comprehensive Logging** – Detailed operation logs
- 🔁 **Error Recovery** – Retry logic with exponential backoff
- 📊 **Tabular Statistics** – Clear migration results
- 💾 **Artifact Export** – Save configurations for comparison

---

## 🔧 **Prerequisites**

- 🐍 Python 3.10+, pip, grpcurl installed
- 🔑 Coralogix API Keys for both source (Team A) and destination (Team B)
- 🌐 Network access to Coralogix APIs
- 👩‍💻 Sufficient permissions to read from Team A and write to Team B

### 🧾 Production Checklist

- [ ]  Valid API keys
- [ ]  Dry runs passed
- [ ]  Backup completed
- [ ]  Maintenance window approved
- [ ]  Monitoring in place

## 🚫 **Not Supported Resources that needs manual setup**

- **Team B Creation:** Must be created manually before using the DR tool.
- **API Keys:** Migration requires specific API keys with read/write permissions — these must be created manually.
- **Groups, Scopes & Custom Roles:** System roles and SSO must be configured manually during the team creation process. *(SCIM integration may be considered in the future.)*
- **Archives:** Team B archives must be configured on a region **different** from Team A’s archives.
- **Quota & Plan Alignment:** Team B should start with a minimal plan that matches Team A’s plan at the beginning of Disaster Recovery.
- **Parsing Rule, Enrichment & Alert Limits:** These limits must be manually set on Team B to match Team A’s configuration.
- **Opensearch Dashboards:** Need to be **manually migrated** into Custom Dashboards.
- **Alerts & Outbound Webhooks:** Excluded from the DR tool as they are managed via **Terraform and the customer’s CI/CD pipeline**.
- **Notification Center:** Supported by Terraform, but **manual routing setup** is still required (only two routing rules: *prod* and *nonprod*).
    
    > 🧭 Support for automatic routing setup is planned in a future release.
    > 
- **Private Actions** and **Private Views:** Cannot be exported or migrated through the DR tool.

---

**TAM Responsibility during DR:**

## 📦 **Installation**

### 1️⃣ Clone the Repository

```bash
git clone https://github.com/cxthulasi/cx-drmigration-tool.git(currently private, needs access) 
cd cx-drmigration-tool

```

### 2️⃣ Setup Virtual Env and Install Dependencies

```bash
chmod +x scripts/setup_venv.sh

./scripts/setup_venv.sh

source venv/bin/activate

pip install -r requirements.txt

```

### 3️⃣ Verify Installation

```bash
python dr-tool.py --help

```

---

## ⚙️ **Configuration**

### 1️⃣ Create Environment File

Create a `.env` file in the root directory or copy from `.env.example`:

**Note:** Be cautious your  source TEAMA key should be readonly and should not have delete permissions just in case if any manual errors in wrongly updating .env files below

```bash
# Coralogix DR Tool Environment Variables

# Team A (Source) Configuration
CX_API_KEY_TEAMA=your-team-a-api-key
CX_API_URL_TEAMA=https://api.ap1.coralogix.com/mgmt/openapi
CX_TEAMA_URL=  # Used for replacing URLs in custom actions

# Team B (Target) Configuration
CX_API_KEY_TEAMB=your-team-b-api-key
CX_API_URL_TEAMB=https://api.eu2.coralogix.com/mgmt/openapi
CX_TEAMB_URL=   # Used for replacing URLs in custom actions

# Optional: Logging Configuration
LOG_LEVEL=INFO
LOG_FORMAT=json

# Optional: Rate Limiting
API_RATE_LIMIT_PER_SECOND=10
API_RETRY_MAX_ATTEMPTS=3
API_RETRY_BACKOFF_FACTOR=2

# Grafana Configuration

TEAMA_HOST=https://ng-api-http.ap1.coralogix.com/grafana
TEAMB_HOST=https://ng-api-http.eu2.coralogix.com/grafana
TEAMA_KEY=your-team-a-api-key
TEAMB_KEY=your-team-b-api-key

```

### 2️⃣ API Key Setup

1. Get Team A API Key → Settings → API Keys → Create Management Key
2. Get Team B API Key → Settings → API Keys → Create Management Key
3. Ensure correct permissions (read for A, write for B)

### 3️⃣ API URL Examples

```bash
CX_API_URL_TEAMA=https://api.coralogix.com/mgmt          # EU1
CX_API_URL_TEAMB=https://api.eu2.coralogix.com/mgmt      # EU2

```

---

## 🚀 Little bit about the tool

**🧭 Entry Point:** `dr-tool.py`

This is the main entry point for the DR migration tool. It defines key orchestration methods responsible for creating service instances and managing the migration flow.

**⚙️ Key Methods:**

- **`create_service`** → A factory function that creates service instances from `src/service/<service_name>.py` and runs them with user options.
- **`run_all_services`** → The main function to sync all the services from **TeamA** to **TeamB**. You can add the services that you want to include for migration here as well.

**📁 src Folder Structure:**

- **`src/`** → Contains the core implementation for all services and logic. Each service module under `src/service/` represents a specific integration or data migration component.

```jsx
src/
├── core/ (where the base api's and other configs are defined)
│   ├── api_client.py
│   └── base_service.py
     ....
     
├── services/ (actual logic for getting and comparing the artefacts from teama to teamb
│   ├── slo.py
│   └── tco.py
     ... so on
```

## 🚀 **Quick Start**

### ✅ Test Connection

```bash
python dr-tool.py slo --dry-run

```

### 🚚 Your First Migration

```bash
python dr-tool.py slo --dry-run
python dr-tool.py slo

python dr-tool.py custom-dashboards --dry-run
python dr-tool.py custom-dashboards

```

---

## 🛠️ **Available Services**

| Service | Description | Command |
| --- | --- | --- |
| **SLO** | Service Level Objectives | `slo` |
| **Custom Dashboards** | Dashboard configurations | `custom-dashboards` |
| **Views** | Saved views & folders | `views` |
| **TCO** | Cost policies | `tco` |
| **Recording Rules** | Prometheus rule groups | `recording-rules` |
| **Parsing Rules** | Log parsing rules | `parsing-rules` |
| **Enrichments** | Data enrichments | `enrichments` |
| **Alerts** | Alert definitions(removes webhooks and migrates) | `alerts` |
| **Event2Metrics** | Event → Metric rules | `event2metrics` |
| **Custom Actions** | Manage actions | `custom-actions` |

---

## 📖 **Usage Examples**

### 🧩 Basic Commands

```bash
python dr-tool.py <service> --dry-run
python dr-tool.py <service>
python dr-tool.py all
python dr-tool.py all --dry-run

```

### 🔍 Service-Specific

```bash
python dr-tool.py slo --dry-run
python dr-tool.py slo

python dr-tool.py custom-dashboards --dry-run
python dr-tool.py custom-dashboards

```

### ⚙️ Advanced Usage(Exclude services)

```bash
python dr-tool.py all --exclude custom-dashboards views

```

---

## 🔍 **Understanding Output**

### 🧪 Dry Run Example

```
DRY RUN RESULTS - SLOS
============================================================
Team A SLOs: 79
Team B SLOs: 54

Planned:
 - Delete 54 SLOs from B
 - Create 79 from A

```

### ✅ Migration Example

```
SLO MIGRATION RESULTS
============================================================
Team A: 79 | Team B (before): 54
Deleted: 54 | Created: 79
Success rate: 100%
✅ SUCCESS: Team B now matches Team A

```

---

### 🧪 Full Dry Run Example

```jsx
python dr-tool.py all  --dry-run

============================================================
DRY RUN RESULTS - PARSING RULE GROUPS
============================================================
📊 Team A rule groups: 17
📊 Team B rule groups: 8
✅ New rule groups to create in Team B: 1
  + Quota (ID: 14b9ae0d-3ad7-11ef-add4-02eb9fef6cad)
🔄 Changed rule groups to recreate in Team B: 8
  ~ k8s Opentelemetry parsing (Team A ID: cd331660-d566-4623-b9f4-c09ec8a5128c, Team B ID: 02a9271f-1453-4084-84d8-f8397da37de9)
  ~ remove fields (Team A ID: 75cd854c-e5fc-4bac-ba01-2be6656a8512, Team B ID: b250ed7d-d599-4960-8eb6-fbefb370e14c)
  ~ Severity Rules (Team A ID: c5720aa0-73ce-4a03-b41a-8d1ef3b71cb4, Team B ID: 020d0b50-535c-4d4c-a73a-4d13154b56d6)
  ~ Cloudtrail rules (Team A ID: 24765544-59da-45f2-a6cb-fa0ae3c9804f, Team B ID: a2978599-bf94-4966-927c-bfff21a31803)
  ~ topipaddress (Team A ID: f3db97ac-3d7b-4cc5-b4ee-6f471cdf47e8, Team B ID: b6935286-8d00-43b6-af20-e0119680ca2f)
  ~ refined-parsingrule (Team A ID: a4b7b33e-7c77-4e2a-9e92-6e683b8d8ebf, Team B ID: 49578641-7497-4645-a28e-f844177c82bc)
  ~ Change Severity of Elb logs (Team A ID: 25a630c0-0491-4ad0-a46a-531b64f509d1, Team B ID: 8ada107e-cfb9-4b63-a64b-b0a86db6bc64)
  ~ parsing rule for sample application (Team A ID: d9710bea-cbe1-4cd9-b12b-28e46b4391ba, Team B ID: e5dbaec0-f405-4bb7-9235-b34482b6dd26)
📋 Total operations planned: 9
  - Create: 1
  - Recreate: 8
  - Delete: 0
============================================================

============================================================
DRY RUN RESULTS - RECORDING RULE GROUP SETS
============================================================
📊 Team A rule group sets: 2
📊 Team B rule group sets: 163
✅ New rule group sets to create in Team B: 2
  + samplegroup (ID: 01K7M1MPWM8XFPNCKJ67X6ZB4Y)
  + cx:slo:76af8c83-2b65-476f-8f04-d3df1fd954f0 (ID: 01K87VPWWYCZKT0DP470GPYN0K)
🗑️ Rule group sets to delete from Team B: 163
  - filesystem_usage_avz_us_east (ID: 01K8E2VFKJNEQJYA0YXRCDZAN4)
  - cx:slo:d195131f-0676-4d87-87ad-cd4c48d30852 (ID: 01K8E2VH5WG0V0JHF3NTRXSHYR)
  - cx:slo:1c045ba8-04b4-4cd9-bad8-91b219617790 (ID: 01K8E2VHYYKC07W61D5VT1N47K)
  - cx:slo:894f83ca-e970-488b-be89-84f5512e5899 (ID: 01K8E2VKHH4XJQWJ9VBKZHC27J)
  - cx:slo:1283144f-6eb8-4581-b32c-db893bed2e6e (ID: 01K8E2VMAT5RCS5F02C6M1DYZW)
  - cx:slo:86f19921-49f7-444e-9ede-3b504aa19f2e (ID: 01K8E2VN41KHYFE4KQRARJ1HGJ)
  - cx:slo:dade9b92-965a-40c7-9807-93ca97ac5d7c (ID: 01K8E2VNXD6NF3ZHX6RSNVHPZ6)
  - cx:slo:40ef910a-622b-4328-a2e0-8167fdff709d (ID: 01K8E2VPPTPSJNHG7W5E5G6QV9)
  - cx:slo:96efd023-ba06-43ee-abfa-3d222bec7472 (ID: 01K8E2VQFYD0S84B24FEZCKP5X)
  
📋 Total operations planned: 165
  - Create: 2
  - Recreate: 0
  - Delete: 163
============================================================

============================================================
DRY RUN RESULTS - EVENTS2METRICS
============================================================
📊 Team A E2Ms: 12
📊 Team B E2Ms: 9
✅ New E2Ms to create in Team B: 3
  + cx_db_catalog_duration (ID: 61e4fcc8-b2aa-4457-b788-c83301a62311)
  + cx_db_catalog_duration_compact (ID: 9623b614-65a5-4663-84af-07777a918aa3)
  + cx_service_catalog_duration_update (ID: 9cfaf50d-7302-4e0d-971b-3ab2082fdd86)
🔄 Changed E2Ms to recreate in Team B: 7
  ~ cx_db_catalog_apdex_satisfied (Team A ID: 742e377a-3d0f-4b40-b09b-d50caf5f5a5c, Team B ID: 02331e5f-e013-44a2-bbc6-8023e2082ae1)
  ~ SourceIP_Event_Count (Team A ID: 85a293b4-4ce2-4899-87c7-2aaffc73ebf6, Team B ID: 38217579-74c8-4482-90af-8895048c8cc2)
  ~ cx_service_catalog_apdex_satisfied (Team A ID: 981abd5a-361d-4dd1-ac7e-d39b73024092, Team B ID: 4099b6d8-b7c9-4f8b-8336-a3d2fb3f77b8)
  ~ catalogue_latency (Team A ID: a4afa4c7-3212-43c4-b30d-ab141bec704b, Team B ID: 48461bb8-fe45-4a3b-810f-3ec06d97b257)
  ~ cx_db_catalog_apdex_tolerating (Team A ID: c7ab379b-70cd-43db-9885-bb53fff0f134, Team B ID: a938a5de-ef9e-4f8e-b7ac-8cb39d640791)
  ~ cx_serverless_runtime_done (Team A ID: f1803ff8-c625-44d6-92c1-b3902d932973, Team B ID: 1a7b0341-fc97-45e0-bffd-9cb3cd28b10c)
  ~ cx_service_catalog_apdex_tolerating (Team A ID: f66aa59f-9d6e-469e-adc2-e587899a11a8, Team B ID: 41d7860c-0875-4644-b421-0af97c1d14a2)
📋 Total operations planned: 10
  - Create: 3
  - Recreate: 7
  - Delete: 0
============================================================

============================================================
DRY RUN RESULTS - CUSTOM DASHBOARDS
============================================================
📊 Team A dashboards: 21
📊 Team B dashboards: 252
✅ New dashboards to create in Team B: 13
  + AWS ALB (ID: bsGuKOwn6TuwiUtgQ5ANF)
  + Aeries Web CPU by Zone (imported) (ID: lAxVttvJowzGLsaJfYVjc)
  + Host Dashboard (imported) (ID: YuCc4hh00aQgTJAtbQYjl)
  + Log Ingestion Monitoring (imported) (ID: ONDW8miQ1fyRwfszPo9UW)
  + MySQL (ID: mINU7F6HGQYrf9p8gdgyI)
  + PE logs (imported) (ID: 5Ojoy8IWeRy0XDcy85Wqy)
  + System Monitoring - Otel (ID: g2dQD7tbVG94ZAzNF4L1r)
  + Test Sample Dashboard (imported) (ID: 1RGx8iB3ysqBOCwnXphcf)
  + Thulasi custom dashboard (ID: IoUVPbMxWyuzAOEi6A9Bf)
  + custom-dashboard (ID: GgY5GwkoqXFfzmzFQoLVl)
  + data usage metrics (ID: KZxbHaO06k8KN9oQwcEPy)
  + gauge dashboard (ID: oCj01GPdWTX5aRpwFSTxe)
  + metrics-visualization (ID: M9qdtZRKJGbgzgMqs6ewq)
┌───────────────────────────────────────────────────────────────────────────────┐
│ Resource Type │ Total │ Created │ Recreated │ Deleted │ Failed │ Success Rate │
├───────────────────────────────────────────────────────────────────────────────┤
│ Folders       │     6 │      [] │         0 │       0 │      0 │       100.0% │
│ Dashboards    │    21 │      13 │         7 │     245 │      0 │       100.0% │
└───────────────────────────────────────────────────────────────────────────────┘

🔄 Changed dashboards to recreate in Team B: 7
  ~ Adam back-engineering
  ~ Kubernetes Complete Observability - Coralogix Helmchart Supported
  ~ Kubernetes Dashboard - Legacy - KSM, cAdvisor,nodemetrics Supported
  ... and 4 more

🗑️ Dashboards to delete from Team B: 245
  - A dashboard #updated
  - A-test-multiquery
  - A23
  ... and 242 more

📋 Ready to migrate! Run without --dry-run to execute these changes.
================================================================================
┌───────────────┬────────┬────────┬─────────────────────┐
│ Resource Type │ Team A │ Team B │ Status              │
├───────────────┼────────┼────────┼─────────────────────┤
│ Dashboards    │     10 │      0 │ Ready for migration │
│ Folders       │      3 │      1 │ Ready for migration │
└───────────────┴────────┴────────┴─────────────────────┘

📊 MIGRATION SUMMARY
────────────────────────────────────────
Total Team A Resources:           13
  - Dashboards:                   10
  - Folders:                       3
Total Team B Resources:            1
  - Dashboards:                    0
  - Folders:                       1

📋 MIGRATION PROCESS:
1. Run import.sh script to export from Team A
2. Run exports.sh script to export from Team B
3. Compare and analyze differences

⚠️  NOTE: This service uses shell scripts for migration
📁 Exported files will be available in the scripts directory

======================================================================
DRY RUN RESULTS - VIEWS & FOLDERS (Delete All + Recreate All Strategy)
======================================================================
📊 Team A Resources:
   📁 Folders: 1
   📄 Views: 1
📊 Team B Resources:
   📁 Folders: 19
   📄 Views: 101

🎯 PLANNED OPERATIONS:
  Step 1: Delete ALL 101 views from Team B
  Step 2: Delete ALL 19 folders from Team B
  Step 3: Create ALL 1 folders from Team A
  Step 4: Create ALL 1 views from Team A
  Total operations: 122

🗑️ Sample views to be DELETED from Team B (showing first 5):
  - Traces (ID: 109935)
  - Default traces (ID: 109936)
  - DataPrime - Revenue (ID: 109937)
  - DataPrime - Enrich (ID: 109938)
  - DataPrime - Enrich and Calculate (ID: 109939)
  ... and 96 more views

✨ Sample views to be CREATED in Team B (showing first 5):
  - sampleview

🎯 EXPECTED RESULT:
  Team B will have 1 folders and 1 views (same as Team A)
======================================================================
┌────────────────┬────────┬────────┬───────────┬───────────┬────────────┐
│ Resource Type  │ Team A │ Team B │ To Delete │ To Create │ Operations │
├────────────────┼────────┼────────┼───────────┼───────────┼────────────┤
│ Custom Actions │      0 │     56 │        56 │         0 │         56 │
└────────────────┴────────┴────────┴───────────┴───────────┴────────────┘

📊 MIGRATION SUMMARY
────────────────────────────────────────
Total Team A Actions:              0
Total Team B Actions:             56
Actions to Delete:                56
Actions to Create:                 0
Total Operations:                 56

⚠️  IMPORTANT: ALL existing custom actions in Team B will be DELETED and recreated from Team A

============================================================
DRY RUN RESULTS - SLOS (Delete All + Recreate All Strategy)
============================================================
📊 Team A SLOs: 1
📊 Team B SLOs: 79

🎯 PLANNED OPERATIONS:
  Step 1: Delete ALL 79 SLOs from Team B
  Step 2: Create ALL 1 SLOs from Team A
  Total operations: 80

🗑️ Sample SLOs to be DELETED from Team B (showing first 5):
  - Amir_Time_Window (ID: c3fe2139-11ff-4d19-8243-7f48897a15f1)
  - Amir_test_Time_window (ID: a83cab8e-7302-4cf8-901f-c583e4e21813)
  - Rahul Test - CPU Utilisation SLO (ID: 5d4b0b58-c1eb-41b4-8885-74037e3ec54e)
  - Health of Env (ID: 20094abd-b483-4b6e-afca-57083aaf87ed)
  - netanel test slo (ID: 6120b7d7-4a92-43f8-bc0b-bbe77494678c)
  ... and 74 more SLOs

✅ Sample SLOs to be CREATED in Team B (showing first 5):
  + API Availability SLO

🎯 EXPECTED RESULT:
  Team B will have 1 SLOs (same as Team A)
  📉 Team B will lose 78 SLOs
============================================================
┌─────────────────────────┬────────┬────────┬───────────┬───────────┬────────────┐
│ Source Type             │ Team A │ Team B │ To Delete │ To Create │ Operations │
├─────────────────────────┼────────┼────────┼───────────┼───────────┼────────────┤
│ SOURCE_TYPE_UNSPECIFIED │      2 │      2 │         2 │         2 │          4 │
│ SOURCE_TYPE_LOGS        │      2 │      2 │         2 │         2 │          4 │
│ SOURCE_TYPE_SPANS       │      0 │      0 │         0 │         0 │          0 │
└─────────────────────────┴────────┴────────┴───────────┴───────────┴────────────┘

📊 MIGRATION SUMMARY
────────────────────────────────────────
Archive Retentions:      
  Team A Retentions:               4
  Team B Retentions:               4
  Missing in Team B:               0
  Retention Mappings:              4

TCO Policies:            
  Total Team A Policies:           4
  Total Team B Policies:           4
  Policies to Delete:              4
  Policies to Create:              4
  Total Operations:                8

⚠️  IMPORTANT: ALL existing policies in Team B will be DELETED and recreated from Team A
```

## 🎛️ **Advanced Features**

### 🔄 Migration Strategy

**Delete All → Recreate All**

1. Delete everything from Team B 
2. Recreate from Team A
3. Ensure full sync

### ⚠️ Error Handling

- Exponential backoff retries
- Failed resource logging
- Partial success continuation
- Comprehensive statistics

### 📁 Artifact Management

```
outputs/
├── slo/
│   ├── slo_teama_latest.json
│   └── slo_teamb_latest.json
├── dashboards/
│   ├── custom-dashboards_teama_latest.json
│   └── custom-dashboards_teamb_latest.json

```

### Logging

```
logs/
├── main/
│   ├── cx-dr-log-slo-2024-10-27-14.log
│   ├── cx-dr-log-all-services-2024-10-27-14.log

```

---

## 🔧 **Troubleshooting**

### 🧩 API Authentication Errors

```bash
# Verify .env keys and permissions

```

### 📉 Resource Count Mismatch

Check logs for failed operations — counts must match.

### ⏱️ Rate Limiting

The tool auto-retries, but you can increase delay if frequent.

### Getting Help

1. Check logs in `logs/`
2. Run `-dry-run` first
3. Compare artifacts in `outputs/`

---

## 📊 **Service-Specific Notes**

- **SLO:** Handles nested IDs, delete-all strategy
- **TCO:** Auto maps archive retentions
- **Dashboards:** Maintains folder hierarchy
- **Views:** Excludes private views
- **Recording Rules:** Cleans read-only fields
- **Enrichments:** All types supported
- **Alerts:** Preserves conditions and webhooks

---

## 🎯 **Best Practices**

✅ Always dry run first

🧾 Check logs for warnings

📊 Verify final counts

💾 Keep backups in `outputs/`

🧪 Test in staging

📡 Monitor API rate limits

🔐 Keep `.env` secure

---

## 🤝 **Contributing**

1. Fork repo
2. Create branch
3. Commit changes
4. Add tests
5. Open PR

---

## 📞 **Support**

- 📚 Documentation: `documentation/`
- 🪵 Logs: `logs/` directory
- 💾 Artifacts: `outputs/` directory

---

========================================================================

# Cloudformation for EC2 with otel and prerequisites installed.

The repo has two cfn templates.

1. vpc.yaml (for vpc and network requirements for the ec2 to be placed)

2. ec2-otel.yaml (ec2 with otel installed)

📌 **Deployment (AWS CLI)**
Note: Assuming you have configured your awscli. You directly deploy using aws console as well.

```jsx
# ADJUST/RENAME PARAMETERS AS PER YOUR NEEDS
aws cloudformation create-stack \
  --stack-name otel-ec2-stack \
  --template-body file://template.yaml \
  --parameters \
      ParameterKey=InstanceType,ParameterValue=t3.micro \
      ParameterKey=ExistingVpcId,ParameterValue=your-vpc-id \
      ParameterKey=ExistingSubnetId,ParameterValue=your-subnet-id \
      ParameterKey=KeyPairName,ParameterValue=my-key-pair \
      ParameterKey=MyIpAddress,ParameterValue=your-ip-address \
      ParameterKey=CoralogixDomain,ParameterValue=cx-domain \
      ParameterKey=CoralogixPrivateKey,ParameterValue=your-private-key \
      ParameterKey=CoralogixApp,ParameterValue=your-application-name \
      ParameterKey=CoralogixSubsystem,ParameterValue=your-subsystem-name \
      ParameterKey=AL2023AmiParameter,ParameterValue=/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64 \
      ParameterKey=OTELVersion,ParameterValue=0.135.0 \
  --capabilities CAPABILITY_NAMED_IAM \
  --region REGION

```
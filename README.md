# Coralogix Disaster Recovery procedure

[**Description	3**](#description)

[**Prerequisites	3**](#prerequisites)

[**Preparation	3**](#preparation)

[Limitations	4](#limitations)

[**Disaster Recovery Syncing (DRS) tool	4**](#disaster-recovery-syncing-\(drs\)-tool)

[Overview	4](#overview)

[Key Features:	4](#key-features:)

[Prerequisites	4](#prerequisites-1)

[Create API Keys	5](#create-api-keys)

[Disaster Recovery Tool on EC2 instance	6](#disaster-recovery-tool-on-ec2-instance)

[Cloudformation for EC2 with Opentelemetry Collector and prerequisites installed.	6](#cloudformation-for-ec2-with-opentelemetry-collector-and-prerequisites-installed.)

[Installation	8](#installation)

[Configuration	8](#configuration)

[The first synchronization	9](#the-first-synchronization)

[Important Directories and Files	19](#important-directories-and-files)

[Set the process to run every day	20](#set-the-process-to-run-every-day)

[**Disaster Recovery Tool on K8s cluster	21**](#disaster-recovery-tool-on-k8s-cluster)

[Safety Check Process	22](#safety-check-process)

[Troubleshooting	22](#troubleshooting)

[**Dashboard	23**](#dashboard)

[**Create alert	24**](#create-alert)

[Alert 1	24](#alert-1)

[Alert 2	24](#alert-2)

[**Disaster Incident	25**](#disaster-incident)

[Set Quota for Team B	25](#set-quota-for-team-b)

[Data Sources (as of document creation)	25](#data-sources-\(as-of-document-creation\))

[Kubernetes clusters	25](#kubernetes-clusters)

[Real User Monitoring	26](#real-user-monitoring)

[AWS Metrics from CloudWatch	26](#aws-metrics-from-cloudwatch)

[**Reverting Changes After the Disaster Incident	26**](#reverting-changes-after-the-disaster-incident)

[Confirm Team A Availability	26](#confirm-team-a-availability)

[Redirect Traffic Back to Team A	27](#redirect-traffic-back-to-team-a)

[Revert Quota Changes	27](#revert-quota-changes)

# 

# Description {#description}

This procedure describes all steps which need to be performed before, during and after the Coralogix region disaster to move traffic to Coralogix from one team to another which are hosted in two different regions.

Naming convention:  
Team A \- it is the source team in Region A, for example in ap-south-1 (Mumbai)  
Team B \- it is the source team in Region B, for example in ap-southeast-1 (Singapore)

Note:   
The GitHub link repository to this tool: [https://github.com/cxthulasi/cx-drs-tool](https://github.com/cxthulasi/cx-drs-tool)

# Prerequisites {#prerequisites}

1. Disaster Recovery Syncing (DRS) tool

# Preparation {#preparation}

Steps below describe how to prepare the team B before setting the Disaster Recovery Syncing tool:

1. Create TeamB  
   [https://coralogix.com/docs/user-guides/account-management/user-management/create-and-manage-teams/](https://coralogix.com/docs/user-guides/account-management/user-management/create-and-manage-teams/)  
2. Ask the Coralogix Support Team to set alerts, parsing rules, enhancements and other limits. Provide the Team A URL and the Team B URL.  
3. Ask the Coralogix Support Team to create a plan with minimal quota size.  
4. Configure SSO on Team B if configured on TeamA  
   [https://coralogix.com/docs/user-guides/account-management/user-management/sso-with-saml/](https://coralogix.com/docs/user-guides/account-management/user-management/sso-with-saml/)  
5. Configure Groups & Scopes, System Custom Roles on Team B if configured on TeamA.  
   [https://coralogix.com/docs/user-guides/account-management/user-management/assign-user-roles-and-scopes-via-groups/create-and-manage-groups/](https://coralogix.com/docs/user-guides/account-management/user-management/assign-user-roles-and-scopes-via-groups/create-and-manage-groups/)  
   [https://coralogix.com/docs/user-guides/account-management/user-management/scopes/](https://coralogix.com/docs/user-guides/account-management/user-management/scopes/)  
   [https://coralogix.com/docs/user-guides/account-management/user-management/create-roles-and-permissions/](https://coralogix.com/docs/user-guides/account-management/user-management/create-roles-and-permissions/)  
6. Configure S3 archive buckets and archive retentions (same as TeamA) for Team B which will be hosted on the same AWS region as Team B  
   [https://coralogix.com/docs/user-guides/data-flow/s3-archive/connect-s3-archive/](https://coralogix.com/docs/user-guides/data-flow/s3-archive/connect-s3-archive/)  
7. Opensearch Dashboards are **not supported** by the Disaster Recovery Syncing tool. Re-create Opensearch dashboards as Custom Dashboards.  
   [https://coralogix.com/docs/user-guides/custom-dashboards/introduction/](https://coralogix.com/docs/user-guides/custom-dashboards/introduction/)  
8. Alerts and outbound webhooks are not supported by the DRS tool.  They should be managed by Terraform and the customer’s CI/CD.  
   Note: Notification Center \- It is supported by Terraform but there will be a need to set the routing manually. This part will be supported soon.  
   [https://coralogix.com/docs/user-guides/notification-center/routing/introduction/](https://coralogix.com/docs/user-guides/notification-center/routing/introduction/)

### Limitations {#limitations}

Private Actions and Private Views can’t be exported by the DRS tool. It means that if a user has his own Views and/or Actions then he will not be able to find them on Team B. 

# Disaster Recovery Syncing (DRS) tool {#disaster-recovery-syncing-(drs)-tool}

## Overview {#overview}

The Disaster Recovery Syncing (DRS) tool automates the process of migrating Coralogix configurations between teams, ensuring disaster recovery readiness and environment synchronization.

### Key Features: {#key-features:}

* 🧪 **Dry Run Mode** – Preview changes before execution  
* 📜 **Comprehensive Logging** – Detailed operation logs  
* 🔁 **Error Recovery** – Retry logic with exponential backoff  
* 📊 **Tabular Statistics** – Clear migration results  
* 💾 **Artifact Export** – Save configurations for comparison

## Prerequisites {#prerequisites-1}

* 🐍 Python 3.10+, pip, grpcurl installed  
* 🔑 Coralogix API Key for the source (Team A) \- only read permissions \- see steps below  
* 🔑 Coralogix API Key for the destination (Team B) \- only read and write permissions \- see steps below  
* 🌐 Network access to Coralogix APIs

### Create API Keys {#create-api-keys}

9. Log into Coralogix Team A.  
10. Click on **Settings** from the left side menu.  
11. Click on **API Keys** at the Users & Teams section  
12. Click on **\+ Personal Key** button.  
13. Put the name for the key. Example: DRS \- TeamA Source.  
14. Choose the following permissions:  
    View Team Actions  
    View User Actions  
    View Configurations for Native Integrations (Contextual Data)  
    View Public Custom Dashboards  
    View Archive Bucket Settings (Logs)  
    View Archive Bucket Settings (Metrics)  
    View AWS Enrichment Configuration  
    View Geo Enrichment Configuration  
    View Unified Threat Intelligence Enrichment Configuration  
    View Custom Enrichment Configuration  
    View Custom Enrichment Data  
    View Events2Metrics Configuration (Logs)  
    View Events2Metrics Configuration (Spans)  
    View Extensions  
    View Grafana Dashboards  
    View Deployed Integrations  
    View Parsing Rules  
    View Recording Rules  
    View Public Saved Views in Explore Screen  
    View Private Saved Views in Explore Screen  
    View SLO Based Alert Settings  
    View SLO Settings  
    View Logs TCO Policies  
    View Tracing TCO Policies  
    View Metrics TCO Policies  
15. Log into Coralogix Team B.  
16. Click on **Settings** from the left side menu.  
17. Click on **API Keys** at the Users & Teams section  
18. Click on **\+ Personal Key** button.  
19. Put the name for the key. Example: DRS \- TeamB Destination.  
20. Choose the following presets:  
    ContextualData  
    Dashboards  
    Events2Metrics  
    Extensions  
    Enrichments  
    Grafana  
    Integrations  
    ParsingRules  
    RecordingRules  
    SavedViews  
    TCOPolicies  
    DataSetup  
    Actions  
    SLO

## Disaster Recovery Tool on EC2 instance {#disaster-recovery-tool-on-ec2-instance}

The Disaster Recovery Syncing (DRS) tool logs to files on the filesystem. To collect those logs Opentelemetry Collector will be needed. Create an EC2 instance using AWS Cloudformation.

### Cloudformation for EC2 with Opentelemetry Collector and prerequisites installed. {#cloudformation-for-ec2-with-opentelemetry-collector-and-prerequisites-installed.}

**Note: Use it if you want to deploy the DRS tool on an EC2 instance.**

Open [`https://github.com/cxthulasi/cx-drs-tool.git`](https://github.com/cxthulasi/cx-drs-tool.git) and download two cfn templates.

1. vpc.yaml (for vpc and network requirements for the EC2 to be placed)  
2. ec2-otel.yaml (EC2 with Opentelemetry Collector installed)

**Deployment (AWS CLI)** 

Note: Assuming you have configured your awscli. You directly deploy using aws console as well.

Deploy VPC stack if there is no VPC already:

```shell
aws cloudformation create-stack \
  --stack-name CFN_STACK_NAME \
  --template-body file://vpc.yaml 
```

Deploy EC2 Stack. Get the VPCID, SUBNETID from the vpc stack outputs or use the existing VPC details as params for networking.

```shell
aws cloudformation create-stack \
  --stack-name otel-ec2-stack \
  --template-body file://ec2-otel.yaml \
  --parameters \
      ParameterKey=InstanceType,ParameterValue=t3.micro \
      ParameterKey=ExistingVpcId,ParameterValue=your-vpc-id \
      ParameterKey=ExistingSubnetId,ParameterValue=your-subnet-id \
      ParameterKey=KeyPairName,ParameterValue=my-key-pair \
      ParameterKey=MyIpAddress,ParameterValue=your-ip-address \
      ParameterKey=CoralogixDomain,ParameterValue=cx-domain \
      ParameterKey=CoralogixPrivateKey,ParameterValue=send-your-data-key \
      ParameterKey=CoralogixApp,ParameterValue=your-application-name \
      ParameterKey=CoralogixSubsystem,ParameterValue=your-subsystem-name \
      ParameterKey=AL2023AmiParameter,ParameterValue=/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64 \
      ParameterKey=OTELVersion,ParameterValue=0.135.0 \
  --capabilities CAPABILITY_NAMED_IAM \
  --region REGION
```

### Installation {#installation}

1. Log into EC2 instance.  
2. Clone the repository

```shell
git clone https://github.com/cxthulasi/cx-drs-tool.git 
cd cx-drs-tool
```

3. Setup Virtual Env and Install Dependencies

```shell
chmod +x scripts/setup_venv.sh
./scripts/setup_venv.sh
source .venv/bin/activate
pip install -r requirements.txt
```

4. Verify Installation

```shell
python drs-tool.py --help
```

### Configuration {#configuration}

1. Log into EC2 instance if you have been logged out.   
2. If you are not inside the cx-drs-tool:  
   `cd cx-drs-tool`  
3. Create Environment File  
   Create a `.env` file or copy from `.env.example`:  
   **Note:** Be cautious your source TEAMA key should be readonly and should not have delete permissions just in case if any manual errors in wrongly updating .env files below

```shell
# Coralogix DRS Tool Environment Variables

# Team A (Source) Configuration
CX_API_KEY_TEAMA=your-team-a-api-key # READONLY KEY WITH REQUIRED PERMISSIONS
CX_API_URL_TEAMA=https://api.eu1.coralogix.com/mgmt/openapi
# Grafana Endpoint Configuration
TEAMA_HOST=https://ng-api-http.eu1.coralogix.com/grafana
CX_TEAMA_URL= https://hs-prod.coralogix.com # Used for replacing URLs in custom actions

# Team B (Target) Configuration
CX_API_KEY_TEAMB=your-team-b-api-key
CX_API_URL_TEAMB=https://api.eu2.coralogix.com/mgmt/openapi
# Grafana Endpoint Configuration
TEAMA_HOST=https://ng-api-http.eu2.coralogix.com/grafana
CX_TEAMB_URL= https://hs-prod-dr.app.eu2.coralogix.com  # Used for replacing URLs in custom actions

# Optional: Logging Configuration
LOG_LEVEL=INFO # use ERROR for production to reduce noise   
LOG_FORMAT=json

# Optional: Rate Limiting
API_RATE_LIMIT_PER_SECOND=10
API_RETRY_MAX_ATTEMPTS=3
API_RETRY_BACKOFF_FACTOR=2


```

### The first synchronization {#the-first-synchronization}

Run the following command to do the dry-run:

```shell
python drs-tool.py all --dry-run
```

Dry Run Example:

```shell

============================================================
DRY RUN RESULTS - PARSING RULE GROUPS (DELETE & RECREATE ALL)
============================================================
📊 Team A rule groups: 56
📊 Team B rule groups: 55
🗑️ Rule groups to delete from Team B: 55
  - OTEL -> filebeat (ID: 5ab5484f-b66c-4b64-bb15-733f8d291abc, Order: 1)
  - k8s Opentelemetry parsing (ID: 7a33a07c-ee63-436d-bb29-0c62ec18465e, Order: 2)
  - Aws status events rules (ID: 048cd168-a86a-491c-a02c-85e4a8216b62, Order: 3)
  - Mapping exception for message field (ID: 56722372-676e-462e-ac53-1afa114fb1d5, Order: 4)
  - Loggregation fix: Extract nested message from message_object (ID: e78b84d1-6859-4e76-b415-1d71ce54bd2b, Order: 5)
  - Severity Rules (ID: 0f8c887f-9bee-4582-b505-43432fe9d741, Order: 6)
  - Block PC Unwanted Logs (ID: bcaa948c-d730-4376-bd44-aaaa17ab20b7, Order: 7)
  - Block PA unwanted logs (ID: 777e5525-9deb-4022-a57a-cb6bb4edfdd3, Order: 8)
  - PC rocky unwanted logs  (ID: d72548b8-6dc5-4c6a-bc7b-e4da56079035, Order: 9)
  - SSAI Block Failed to Fetch Manifest HTTP 404 Error Logs (ID: 50bb9ea1-e49e-449e-829d-bd24f45ed159, Order: 10)
  - Severity Rules (ID: 85245f09-bc4b-4384-9c9b-6e933cec1922, Order: 11)
  - Ceph MDS (ID: f46dadd1-3bcb-4946-b30b-5a413e59c8a4, Order: 12)
  - New Group (ID: db96146e-5821-4079-bd50-7cbe447a4b7a, Order: 13)
  - Extract server API Error (ID: bd1d01a2-a4ec-45a9-837a-ed683b448982, Order: 14)
  - Severity Rules for non prod (ID: 33292b76-1437-4828-a423-7e7884564a6c, Order: 15)
  - Extract server API Error for non prod (ID: 8edadb5e-279f-42b6-9ef0-bac27b743f79, Order: 16)
  - mygroup (ID: e14c1438-8e38-489f-8eee-fee8aedb2c69, Order: 17)
  - fix mapping exception for message with Object (ID: f3c908a2-dab8-478e-bbe9-ec9294ebc394, Order: 18)
  - UM-Concurrency-rule (ID: 5b843d4f-8ef6-449b-a464-4ea43e4bf8b6, Order: 19)
  - Block LaunchDarkly Warning Logs (ID: 51762f31-6434-451f-be55-5490692ec511, Order: 20)
  - [PC]: blocking "Empty or null maturityLevel in userToken" (ID: ac996aa6-f4fa-4a27-88b1-8c89074fad74, Order: 21)
  - Received GetPlaybackURL request with passport data (ID: 339c43b6-52e4-41cc-93d2-dee61f188a49, Order: 22)
  - Received request in GetPlaybackURL of graphql service (ID: 46d45d84-c218-421b-97db-56b6fb31df28, Order: 23)
  - Blocking communication otp logs (ID: 39da4f32-02aa-4516-912e-b9ccc2ecbfb2, Order: 24)
  - Block PC UnWanted Logs (ID: e47e0a48-b91a-458e-9c0a-b86f7f1e7d1c, Order: 25)
  - Parse HS-core Logs (ID: 2de416f4-8c09-45d8-baa3-a3552d08fd91, Order: 26)
  - Block specific logs (ID: b785fe58-d760-48cb-b302-7042e755bfce, Order: 27)
  - Sample logs (ID: 2655fd37-2fad-4f45-abe9-b46b8ffafce9, Order: 28)
  - zplay-rules (ID: 8a84d326-d47a-4082-bfdb-a49023d5e7c0, Order: 29)
  - Fix Mapping Exception (ID: ed8113c2-6204-426d-a8fe-dcdfb7a4f6a0, Order: 30)
  - Subscription | Block country backfill logs And Block Offer Service Logs in subs (ID: 176d9879-9497-4eae-9a87-910024a26738, Order: 31)
  - Block Country Code Fallback Logs | For Different PGs (ID: a980f4f2-4fc8-40f2-8422-a3e2fe8360ec, Order: 32)
  - Block Coupon Service GetOffer Logs (ID: 03858570-8ee1-42de-9dac-ca393e42050f, Order: 33)
  - Hspay Debug and Info Log (ID: 871bac48-1e69-43d1-8e42-fed1c0c262c4, Order: 34)
  - Block unwanted subs info/error logs (ID: fcb750f7-5602-493c-9bd4-9f0c827cceb3, Order: 35)
  - Parse Useful Fields from Adtech (ID: 2747d522-04f6-44fe-a759-ded13f9fadb2, Order: 36)
  - Parse Useful Fields from CMS (ID: cf8ee679-7551-4b63-8390-d8d96bce24df, Order: 37)
  - Block Prefetch Service (ID: f3d62551-ab93-462d-a8fe-f9631b390e85, Order: 38)
  - Block Programmatic decision service (ID: a6637615-0e81-4e6c-a61b-0c5fd71f6c5b, Order: 39)
  - Block lp service (ID: b1d72d76-44b5-4ad8-83ab-cd952cb7f920, Order: 40)
  - Parse useful field for Consumption application (ID: f4ed2ad5-e4c3-4d20-aad4-60cd6e453626, Order: 41)
  - Block empty gam id log (ID: 5820cdf6-2a61-44ab-a96d-319bf4777eb5, Order: 42)
  - Extract ERR_PB_*  errors from logs  (ID: a7125fa7-cb2d-40eb-a354-53268c09ac81, Order: 43)
  - Suppress com.hotstar.lp.validator.Validator (ID: 39d8d11e-52fd-47c3-a7f6-c59c9d3ad1f9, Order: 44)
  - Cx-Teodor | Fixing mapping exception for PageLayoutFilters (ID: 214b8a3e-c31d-4df3-b925-2715e5e2ed5b, Order: 45)
  - Block Trivial logs (ID: b3580616-270d-4bb9-ac9d-5ea0b47d4fce, Order: 46)
  - Block audience platform hedwig logs (ID: 37d69fbb-dfc4-41d1-900f-2f531d984abf, Order: 47)
  - Block CMS multi-get queue lenght health check log (ID: ec0ac738-4020-4afb-8686-3b10ea76101c, Order: 48)
  - Shifu Cohort CTR Block (ID: 7990f734-f416-49ad-9837-c62ef506e2f6, Order: 49)
  - Block FCAP (ID: db2de377-07b4-44f2-b834-9ddd9f88fa63, Order: 50)
  - CX-Stefaena (ID: 326cfb87-50ac-448f-8d8a-fef8fa665995, Order: 51)
  - Extract trace_id and span_id from all application logs or transform traceId/spanId (ID: 08c8cc4b-3291-480d-878a-9d293cd32c4e, Order: 52)
  - Block Consumption log message (ID: 07b44159-f612-4cc7-92a6-994d95fe4ec1, Order: 53)
  - Parse Inner message json fields (ID: 9e7bada4-00eb-4fa4-9e4c-288f669fcfda, Order: 54)
  - Block AB logs for persona (ID: 38acc5eb-c795-4c0f-8456-9484e9e87741, Order: 55)
📄 Rule groups to create from Team A: 56
  + OTEL -> filebeat (ID: b8cf20d6-73a9-4ba5-80d1-1055e3c7e1cf, Order: 1)
  + k8s Opentelemetry parsing (ID: 27e39abd-db61-4b75-acb7-d33338bc63ca, Order: 2)
  + Aws status events rules (ID: 4b1352f7-1613-48e3-aa9f-b0f52794b30e, Order: 3)
  + Mapping exception for message field (ID: 5734dd7e-ccb0-11ea-8856-06364196e782, Order: 4)
  + Loggregation fix: Extract nested message from message_object (ID: 1391569e-f9a0-6e08-0170-ec434e2ab4f6, Order: 5)
  + Severity Rules (ID: 4d1dee1d-a472-11e8-984b-02420a000706, Order: 6)
  + Block PC Unwanted Logs (ID: d9e1c73e-01c8-4f4d-92f3-c3c9b40bc99a, Order: 7)
  + Block PA unwanted logs (ID: c5487321-7cbf-4d10-9773-7d1479e6648d, Order: 8)
  + PC rocky unwanted logs  (ID: be93a724-15f0-4be4-9888-1d28e6e064da, Order: 9)
  + SSAI Block Failed to Fetch Manifest HTTP 404 Error Logs (ID: ba26a803-9c39-4221-a159-540f953bce6c, Order: 10)
  + Severity Rules (ID: 68c008a6-7a8d-4f58-bb44-42a546b7a98b, Order: 11)
  + Ceph MDS (ID: 159de70a-e0db-4e3d-944d-372bc2a5df59, Order: 12)
  + New Group (ID: 9a37f05b-31ea-4fde-b7ca-570b4713564b, Order: 13)
  + Extract server API Error (ID: 78a37334-206e-49ec-8779-6962a21c0223, Order: 14)
  + Severity Rules for non prod (ID: 61a92468-fd35-4bd7-8dc9-c8249def1517, Order: 15)
  + Extract server API Error for non prod (ID: a6259d86-79b5-415b-b463-6a9c5a86c231, Order: 16)
  + mygroup (ID: 379eaad3-0c06-4a05-a4a8-6eb325ebbee0, Order: 17)
  + fix mapping exception for message with Object (ID: 5edcc290-fd8d-4260-9c12-0a174ca75e5e, Order: 18)
  + UM-Concurrency-rule (ID: 04bdaad8-e4f5-4bc7-aa1f-eb064b68a601, Order: 19)
  + Block LaunchDarkly Warning Logs (ID: 5cb7e7e3-7f6d-43fd-9891-b3fa20873129, Order: 20)
  + [PC]: blocking "Empty or null maturityLevel in userToken" (ID: c35d8eb1-c19f-4760-a230-5fa9dc91d630, Order: 21)
  + Received GetPlaybackURL request with passport data (ID: a890aa02-a188-4e13-98ae-a8e98daae462, Order: 22)
  + Received request in GetPlaybackURL of graphql service (ID: 59a36fba-5fe7-4d7e-af5c-19d108d63c25, Order: 23)
  + Blocking communication otp logs (ID: 2664142c-9240-4d99-b5f1-626ab9864176, Order: 24)
  + Block PC UnWanted Logs (ID: f5eebbf7-6b47-40e9-80c0-31c5fafef646, Order: 25)
  + Parse HS-core Logs (ID: 75660865-0e4c-4045-8abd-881a7a152207, Order: 26)
  + Block specific logs (ID: b6bf9218-6bbb-4218-8ae2-440d27bb759f, Order: 27)
  + Sample logs (ID: 421ce603-4bb2-4fde-abc0-466490f39c44, Order: 28)
  + zplay-rules (ID: ff8338c7-b6a0-475c-a435-c3a43e3aca91, Order: 29)
  + Fix Mapping Exception (ID: c6fc4613-3efb-464e-b0ed-52b6052c7c86, Order: 30)
  + Subscription | Block country backfill logs And Block Offer Service Logs in subs (ID: c3cb8bfb-a201-427a-8df8-8097e25e9d78, Order: 31)
  + Block Country Code Fallback Logs | For Different PGs (ID: 9f1ddc3e-2e6c-4e02-8411-5e51e4b95202, Order: 32)
  + Block Coupon Service GetOffer Logs (ID: f1b6c747-eef0-4116-a3f3-e928ebbe05cc, Order: 33)
  + Hspay Debug and Info Log (ID: ec5d1afd-c4de-4d04-99bd-6592ec68e158, Order: 34)
  + Block unwanted subs info/error logs (ID: 55a80c91-e1a3-4ab2-a06f-a3eea82c5c17, Order: 35)
  + Parse Useful Fields from Adtech (ID: ac834665-5d0b-8178-d7b9-92f768700d53, Order: 36)
  + Parse Useful Fields from CMS (ID: e1c76ab4-1097-d115-d0bd-a8b78cf41bbb, Order: 37)
  + Block Prefetch Service (ID: d959d079-5693-a168-ff2d-cb2015553a98, Order: 38)
  + Block Programmatic decision service (ID: ecfa1018-c9f0-d533-e1ed-7b0eae416e74, Order: 39)
  + Block lp service (ID: 03753e43-a3db-41ba-81e0-31dcc660fb9e, Order: 40)
  + Parse useful field for Consumption application (ID: 8bfd75d2-7c6d-59e5-3c36-3c0b23a48047, Order: 41)
  + Block empty gam id log (ID: d4496f8b-cc0c-42f0-12f5-e8932df92ddb, Order: 42)
  + Extract ERR_PB_*  errors from logs  (ID: 09e4a0b3-a3d0-5bbf-fdef-f82e0bf2bf24, Order: 43)
  + Suppress com.hotstar.lp.validator.Validator (ID: f255b2f1-3257-514e-930f-e4a6f103379f, Order: 44)
  + Cx-Teodor | Fixing mapping exception for PageLayoutFilters (ID: 7a3b9746-f879-4925-9d6f-ebe0908129d6, Order: 45)
  + Block Trivial logs (ID: ee2837b7-0ff0-49ce-933d-8910bf74caf4, Order: 46)
  + Block audience platform hedwig logs (ID: ccd59a6a-0991-4347-8588-1151823e24ed, Order: 47)
  + Block CMS multi-get queue lenght health check log (ID: 0f6baa55-b829-4dd5-82ff-7369cadc18ed, Order: 48)
  + Shifu Cohort CTR Block (ID: 30e87080-88ef-499e-ba90-1aab6207cce8, Order: 49)
  + Block FCAP (ID: 093f149b-aaab-46e8-9645-ee74b303fb93, Order: 50)
  + CX-Stefaena (ID: acba247e-9473-4a6b-be7d-40c82e4e1fdc, Order: 51)
  + Extract trace_id and span_id from all application logs or transform traceId/spanId (ID: cd920d15-9fc9-4ed8-821b-8c9716abd545, Order: 52)
  + Block Consumption log message (ID: 58bb31a1-a702-44a8-847f-6279f3684cda, Order: 53)
  + Parse Inner message json fields (ID: 7da3bc3f-fe77-4825-87ef-0e2aa61c4c3e, Order: 54)
  + Block AB logs for persona (ID: f03ae0e8-c503-416f-90a9-c795933f4fb0, Order: 55)
  + Quota (ID: 30b74c1c-4283-11ea-8856-06364196e782, Order: 9196)
📋 Total operations planned: 111
  - Delete: 55
  - Create: 56

⚠️  IMPORTANT: ALL existing rule groups in Team B will be DELETED and recreated from Team A
🎯 This ensures perfect order synchronization and rule consistency
============================================================

============================================================
DRY RUN - RECORDING RULE GROUP SETS MIGRATION
============================================================
📊 Team A rule group sets: 6
📊 Team B rule group sets (current): 11

🔄 Planned Operations:
   🗑️  Delete ALL 11 rule group sets from Team B
   ✅ Create 6 rule group sets from Team A

📋 Total operations: 17
============================================================

Sample rule group sets from Team A (first 5):
  1. Hotstar_recording_rule.yaml (ID: 01JMEEZRN2JNCSK9JQA2Z5ERF6)
  2. cx:slo:7681fe9d-03f4-4d8b-957b-23135f2a597f (ID: 01K7KS21V38PVN5A3D39AXMSMM)
  3. cx:slo:0bef3430-77ab-483e-8a13-a6bbb66dc652 (ID: 01K9VB4E1Z6TCB62R7AS9S0CDM)
  4. cx:slo:f30d643d-3263-49b3-88d6-328718935809 (ID: 01K9VZ3QFB42E0MW643CTAFKEP)
  5. cx:slo:ca1246c5-daeb-48e5-a7e8-01c4b0267cb4 (ID: 01K9YJBACGK269T1ZE7EBEBJNF)


============================================================
DRY RUN - GENERAL ENRICHMENT RULES MIGRATION
============================================================
📊 Team A enrichments (migratable): 1
📊 Team B enrichments (current): 1

🔄 Planned Operations:
   🗑️  Delete ALL 1 enrichments from Team B
   ✅ Create 1 enrichments from Team A

📋 Total operations: 2
============================================================

Sample migratable enrichments from Team A (first 5):
  1. Unknown (from: client_ip, type: suspiciousIp)


============================================================
DRY RUN - EVENTS2METRICS MIGRATION
============================================================
📊 Team A E2Ms: 14
📊 Team B E2Ms (current): 14

🔄 Planned Operations:
   🗑️  Delete ALL 14 E2Ms from Team B
   ✅ Create 14 E2Ms from Team A

📋 Total operations: 28
============================================================

Sample E2Ms from Team A (first 5):
  1. cx_service_catalog_apdex_satisfied (ID: 0b2e39ce-653f-4723-a8ad-bb66069f1292)
  2. binder_id (ID: 0c7dbaab-4c7d-4907-a3d4-ce9f6748050b)
  3. cx_db_catalog_duration (ID: 1a497ce0-be4c-4142-9aa0-68517697cea7)
  4. cx_serverless_runtime_done (ID: 51e2f7db-c662-4108-b2f5-2b819f483a22)
  5. cx_service_catalog_service_duration (ID: 8397f3a2-e305-4f48-a58d-db34caf195b6)

┌────────────────┬────────┬────────┬───────────┬───────────┬────────────┐
│ Resource Type  │ Team A │ Team B │ To Delete │ To Create │ Operations │
├────────────────┼────────┼────────┼───────────┼───────────┼────────────┤
│ Custom Actions │     16 │     16 │        16 │        16 │         32 │
└────────────────┴────────┴────────┴───────────┴───────────┴────────────┘

📊 MIGRATION SUMMARY
────────────────────────────────────────
Total Team A Actions:             16
Total Team B Actions:             16
Actions to Delete:                16
Actions to Create:                16
Total Operations:                 32

⚠️  IMPORTANT: ALL existing custom actions in Team B will be DELETED and recreated from Team A

============================================================
DRY RUN RESULTS - SLOS (Delete All + Recreate All Strategy)
============================================================
📊 Team A SLOs: 5
📊 Team B SLOs: 5

🎯 PLANNED OPERATIONS:
  Step 1: Delete ALL 5 SLOs from Team B
  Step 2: Create ALL 5 SLOs from Team A
  Total operations: 10

🗑️ Sample SLOs to be DELETED from Team B (showing first 5):
  - ELB-Health-SLO (ID: 0c4505df-1ead-4cb7-bc36-3f77065238f4)
  - ALB Health SLO (ID: 8484848d-9c75-45b1-a4aa-ae58b86a23a5)
  - ELB Teamwise Health - SLO (ID: 1178817b-72e1-4f47-bf27-33b87d8142fa)
  - Baseline RDS Uptime WIP (ID: 9e1df3ae-0bff-4aa4-83fb-238595a517be)
  - 6-9s Uptime RDS (ID: 57ada566-5bdb-416b-a0e5-448a181bb569)

✅ Sample SLOs to be CREATED in Team B (showing first 5):
  + ELB-Health-SLO
  + ALB Health SLO
  + ELB Teamwise Health - SLO
  + Baseline RDS Uptime WIP
  + 6-9s Uptime RDS

🎯 EXPECTED RESULT:
  Team B will have 5 SLOs (same as Team A)
  ✨ Teams are already in sync, but migration will ensure consistency
============================================================

========================================================================================================================
📊 DRY RUN SUMMARY - ALL SERVICES
========================================================================================================================
+---------------------+----------+----------+------------+-----------+-----------+-----------+----------+-----------+-------------+-------------+
| Service             | Status   |   Team A |     Team B |    Team B |   Created |   Deleted |   Failed |   Skipped |   Total Ops | Success %   |
|                     |          |          |   (Before) |   (After) |           |           |          |           |             |             |
+=====================+==========+==========+============+===========+===========+===========+==========+===========+=============+=============+
| parsing-rules       | SUCCESS  |       55 |         55 |        55 |        56 |        55 |        0 |         0 |         111 | 100.0%      |
+---------------------+----------+----------+------------+-----------+-----------+-----------+----------+-----------+-------------+-------------+
| recording-rules     | SUCCESS  |        6 |         11 |         6 |         6 |        11 |        0 |         0 |          17 | 100.0%      |
+---------------------+----------+----------+------------+-----------+-----------+-----------+----------+-----------+-------------+-------------+
| general-enrichments | SUCCESS  |        1 |          1 |         1 |         0 |         0 |        0 |         0 |           0 | 100.0%      |
+---------------------+----------+----------+------------+-----------+-----------+-----------+----------+-----------+-------------+-------------+
| events2metrics      | SUCCESS  |       14 |         14 |        14 |        14 |        14 |        0 |         0 |          28 | 100.0%      |
+---------------------+----------+----------+------------+-----------+-----------+-----------+----------+-----------+-------------+-------------+
| views               | SUCCESS  |       30 |         30 |        30 |        30 |        30 |        0 |         0 |          60 | 100.0%      |
+---------------------+----------+----------+------------+-----------+-----------+-----------+----------+-----------+-------------+-------------+
| custom-actions      | SUCCESS  |       16 |         16 |        16 |        16 |        16 |        0 |         0 |          32 | 100.0%      |
+---------------------+----------+----------+------------+-----------+-----------+-----------+----------+-----------+-------------+-------------+
| slo                 | SUCCESS  |        5 |          5 |         5 |         0 |         0 |        0 |         0 |           0 | 100.0%      |
+---------------------+----------+----------+------------+-----------+-----------+-----------+----------+-----------+-------------+-------------+

────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
📈 OVERALL STATISTICS
────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
Total Services Processed:               7
Successful Services:                    7
Failed Services:                        0
Overall Success Rate:              100.0%
Total Duration:                      4.7s
========================================================================================================================

📄 Detailed summary saved to: outputs/migration-summary/migration-summary-dry-run-2025-12-04-10-19-13.json
📄 Latest summary saved to: outputs/migration-summary/migration-summary-dry-run-latest.json
📄 Coralogix logs saved to: outputs/migration-summary/coralogix-logs-dry-run-2025-12-04-10-19-13.jsonl
📄 Coralogix logs (latest) saved to: outputs/migration-summary/coralogix-logs-dry-run-latest.jsonl

========================================================================================================================
📊 MIGRATION SUMMARY (JSON FORMAT FOR MONITORING)
========================================================================================================================
{"log_type": "migration_summary", "runtime": "2025-12-04-10-19-08-6601580e", "mode": "DRY RUN", "timestamp": "2025-12-04T10:19:13.683900", "duration_seconds": 4.705614, "total_services": 7, "successful_services": 7, "failed_services": 0, "success_rate": "100.0%"}
{"log_type": "service_detail", "runtime": "2025-12-04-10-19-08-6601580e", "mode": "DRY RUN", "timestamp": "2025-12-04T10:19:13.683900", "service": "parsing-rules", "status": "SUCCESS", "teama_count": 55, "teamb_before": 55, "teamb_after": 55, "created": 56, "updated": 0, "deleted": 55, "failed": 0, "skipped": 0, "total_operations": 111, "success_rate": "100.0%", "error_message": null}
{"log_type": "service_detail", "runtime": "2025-12-04-10-19-08-6601580e", "mode": "DRY RUN", "timestamp": "2025-12-04T10:19:13.683900", "service": "recording-rules", "status": "SUCCESS", "teama_count": 6, "teamb_before": 11, "teamb_after": 6, "created": 6, "updated": 0, "deleted": 11, "failed": 0, "skipped": 0, "total_operations": 17, "success_rate": "100.0%", "error_message": null}
{"log_type": "service_detail", "runtime": "2025-12-04-10-19-08-6601580e", "mode": "DRY RUN", "timestamp": "2025-12-04T10:19:13.683900", "service": "general-enrichments", "status": "SUCCESS", "teama_count": 1, "teamb_before": 1, "teamb_after": 1, "created": 0, "updated": 0, "deleted": 0, "failed": 0, "skipped": 0, "total_operations": 0, "success_rate": "100.0%", "error_message": null}
{"log_type": "service_detail", "runtime": "2025-12-04-10-19-08-6601580e", "mode": "DRY RUN", "timestamp": "2025-12-04T10:19:13.683900", "service": "events2metrics", "status": "SUCCESS", "teama_count": 14, "teamb_before": 14, "teamb_after": 14, "created": 14, "updated": 0, "deleted": 14, "failed": 0, "skipped": 0, "total_operations": 28, "success_rate": "100.0%", "error_message": null}
{"log_type": "service_detail", "runtime": "2025-12-04-10-19-08-6601580e", "mode": "DRY RUN", "timestamp": "2025-12-04T10:19:13.683900", "service": "views", "status": "SUCCESS", "teama_count": 30, "teamb_before": 30, "teamb_after": 30, "created": 30, "updated": 0, "deleted": 30, "failed": 0, "skipped": 0, "total_operations": 60, "success_rate": "100.0%", "error_message": null}
{"log_type": "service_detail", "runtime": "2025-12-04-10-19-08-6601580e", "mode": "DRY RUN", "timestamp": "2025-12-04T10:19:13.683900", "service": "custom-actions", "status": "SUCCESS", "teama_count": 16, "teamb_before": 16, "teamb_after": 16, "created": 16, "updated": 0, "deleted": 16, "failed": 0, "skipped": 0, "total_operations": 32, "success_rate": "100.0%", "error_message": null}
{"log_type": "service_detail", "runtime": "2025-12-04-10-19-08-6601580e", "mode": "DRY RUN", "timestamp": "2025-12-04T10:19:13.683900", "service": "slo", "status": "SUCCESS", "teama_count": 5, "teamb_before": 5, "teamb_after": 5, "created": 0, "updated": 0, "deleted": 0, "failed": 0, "skipped": 0, "total_operations": 0, "success_rate": "100.0%", "error_message": null}
========================================================================================================================
```

Sample Summary Output:

![][image1]

If no errors then run the first synchronization from Team A to Team B.

```shell
python drs-tool.py all
```

### Important Directories and Files {#important-directories-and-files}

[drs-tool.py](http://drs-tool.py) is the entry script   
logs – stores logs for each service;  
src – contains service definitions, helper scripts, and core API logic;  
outputs – holds Team A/Team B service configs and migration summary stats for each run.

## ![][image2]

### Set the process to run every day {#set-the-process-to-run-every-day}

1. Edit cron. Execute:  
   `crontab -e`   
2. `Add the following entries:`

```
30 0 * * * /usr/bin/aws s3 sync /home/ec2-user/cx-drs-tool s3://cx-coe-jiostar-drtool-backup-bucket/cx-drs-tool/ --exclude ".*" --exclude "*/.*" >> /home/ec2-user/s3_sync.log 2>&1

30 1 * * * cd /home/ec2-user/cx-drs-tool && source /home/ec2-user/cx-drs-tool/.venv/bin/activate && /home/ec2-user/cx-drs-tool/.venv/bin/python drs-tool.py all --dry-run >> /home/ec2-user/drs-tool.log 2>&1
```

## 

# Disaster Recovery Tool on K8s cluster {#disaster-recovery-tool-on-k8s-cluster}

The following steps need to be followed if you are going to deploy the DRS tool on K8s cluster.

Note: This configuration assumes that the Coralogix Opentelemetry Helm chart is deployed on K8s cluster. The Opentelemetry Collector will send DRS logs to Coralogix.  
For the code and settings details refer to [https://github.com/cxthulasi/cx-drs-tool/tree/main/k8s-persistent](https://github.com/cxthulasi/cx-drs-tool/tree/main/k8s-persistent)

1. Clone the repository

```shell
git clone https://github.com/cxthulasi/cx-drs-tool.git 
```

2. Enter the directory:

```shell
cd cx-drs-tool 
```

3. Build the image:

```shell
docker build -f k8s-persistent/Dockerfile -t <Docker Hub username / repository namespace>/cx-drs-tool:latest . 
```

4. Push the image to your repo:

```shell
docker push <Docker Hub username / repository namespace>/cx-drs-tool:latest
```

5. Enter the k8s-persistent directory:

```shell
cd k8s-persistent
```

6. Edit the secrets.yaml file.  
   Note: API Keys were created at this section: [Coralogix Disaster Recovery procedure](https://docs.google.com/document/d/1dk2mn-aX1KUNh1KxNBZVRz4SyOFNsJHRNU6quP361os/edit?tab=t.0#heading=h.irmq3zhuhw2d)

```shell
vi secrets.yaml
```

7. Edit the configmap.yaml file.

```shell
vi configmap.yaml
```

8. Deploy the tool.

```shell
# Create namespace
kubectl apply -f namespace.yaml
# Create ConfigMap and Secrets
kubectl apply -f secrets.yamlkubectl apply -f configmap.yaml
# Deploy the pod
kubectl apply -f deployment.yaml
```

9. Verify the deployment.

```shell
# Check if pod is running
kubectl get pods -n cx-drs
# View pod logs
kubectl logs -n cx-drs -l app=cx-drs-tool -f
# Check deployment status
kubectl get deployment -n cx-drs
```

10. Manual execution.  
    It is recommended to run the DRS tool the first time manually to monitor and verify that the process finished any issues.

```shell
# Trigger migration manually (without waiting for schedule)
POD_NAME=$(kubectl get pods -n cx-drs -l app=cx-drs-tool -o jsonpath='{.items[0].metadata.name}')
kubectl exec -n cx-drs $POD_NAME -- sh -c 'cd /app && python3 -u /app/drs-tool.py all 2>&1 | tee /proc/1/fd/1'

# Trigger S3 sync manually
kubectl exec -n cx-drs $POD_NAME -- sh -c 'cd /app && /usr/local/bin/aws s3 sync /app ${S3_BUCKET_NAME} --exclude ".*" --exclude "*/.*" 2>&1 | tee /proc/1/fd/1'

# Cleanup - Daily at ${CLEANUP_SCHEDULE} UTC (delete files older than 7 days)
kubectl exec -n cx-drs $POD_NAME -- sh -c 'find /app/logs /app/outputs /app/snapshots /app/state /app/src/scripts/dashboards /app/src/scripts/folders -mindepth 1 -mtime +7 -exec rm -rf {} +'

```

## Safety Check Process {#safety-check-process}

For any reason if the TeamA API fails, there is a safety check implemented for each service to safely exit the migration process and not delete any of the TeamB resources. 

## Troubleshooting {#troubleshooting}

* API Authentication Errors

```shell
# Verify .env keys and permissions
```

* Resource Count Mismatch

Check logs for failed operations — counts must match.

* Rate Limiting

The tool auto-retries, but you can increase delay if frequent.

* Getting Help  
- Log into Coralogix and check collected logs  
- Check logs in `logs/`  
- Compare artifacts in `outputs/`

# Dashboard  {#dashboard}

Note: For any reason if TeamA fetching fails, the safety check kicks in and safely exits the migration of the service, status and success\_ratio are updated accordingly.  
Dashboard file: \<github link will be provided\>  
![][image3]

# Create alert {#create-alert}

Create the following alerts to be notified about errors reported by the running DRS tool.

## Alert 1 {#alert-1}

Alert Type: Standard  
Alert Name: DRS Sync Tool \- Synchronization completed with failures  
Alert Description: DRS Sync Tool \- One or more of services was not synchronized. Check DRS Synchronization Dashboard  
Labels:drs-tool  
Search query: mode:"MIGRATION" AND log\_type:"migration\_summary" AND failed\_services.numeric:\[1 TO \*\]  
Applications: drs-tool (adjust it if your application name is different)  
Subsystem: All  
Severities: All  
Conditions:   
Alert when: Notify Immediately  
	Set Condition Rules: when the query matches a log trigger a P2 alert.  
Notifications: set notifications accordingly to the way you want to be notified.

Click on the **Create Alert** button.

## Alert 2 {#alert-2}

Alert Type: Standard  
Alert Name: DRS Sync Tool \- Service failed to sync  
Alert Description: A service failed to sync between Team A and Team B. Check DRS Synchronization Dashboard  
Labels: drs-tool  
Search query: mode:"MIGRATION" AND log\_type:"service\_detail" AND status:"failed"  
Applications: drs-tool (adjust it if your application name is different)  
Subsystem: All  
Severities: All  
Conditions:   
Alert when: More than threshold  
	Set Condition Rules:  
When the number of logs within **10 Minutes**  is more than **0** trigger a P2 alert.  
Group By: service  
Notifications: set notifications accordingly to the way you want to be notified.

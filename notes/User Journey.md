## User ASKs Question:
User types question in Streamlit
        ↓
Streamlit sends HTTP POST to FastAPI
(running locally or on a server)
        ↓
FastAPI receives request
Currently: calls pipeline.py directly (local mode)
Later:     calls API Gateway → query Lambda
        ↓
pipeline.py orchestrates:
    1. Classifier (Nova Micro)
       → is this NDIS/OFF_TOPIC/HARMFUL/SENSITIVE?
       → if blocked: return message immediately
        ↓
    2. Rewriter (Nova Lite)
       → rewrites query for better retrieval
        ↓
    3. Retriever (Bedrock KB)
       → searches S3 Vectors index
       → org_id filter applied — only org's docs + NDIS
       → returns ranked chunks
        ↓
    4. Nova Micro reranker
       → reorders chunks by relevance
        ↓
    5. Memory (DynamoDB + AgentCore)
       → fetches last 5 conversation turns
       → fetches long-term facts about user
        ↓
    6. Generator (Claude Haiku 4.5)
       → builds prompt with context + memory
       → streams answer token by token
        ↓
FastAPI streams response back to Streamlit
        ↓
Streamlit renders answer word by word
        ↓
Turn saved to DynamoDB + AgentCore Memory


## User UPLOADs Documents:
Admin goes to S3 console, uploads new_policy.pdf to sena/misty/orgs/org_name/.

Admin uploads PDF to S3
        ↓
S3 fires ObjectCreated event
        ↓
EventBridge rule matches
(filtered to sena/misty/orgs/ prefix only)
        ↓
sena-misty-auto-ingestion Lambda invoked
        ↓
Lambda:
    1. Extracts org_id from S3 key path
       sena/misty/orgs/org_sunrise/... → org_sunrise
        ↓
    2. Creates registry entry in DynamoDB
       status: INGESTING
        ↓
    3. Creates .metadata.json sidecar in S3
       { "metadataAttributes": { "org_id": "org_sunrise" } }
        ↓
    4. Calls start_ingestion_job()
        ↓
Bedrock KB takes over:
    → Parses PDF → text
    → Hierarchical chunking (1500/300 tokens)
    → Titan V2 embeds every chunk (1024 dimensions)
    → Stores vectors in S3 Vectors with org_id metadata
        ↓
Lambda polls until COMPLETE
        ↓
Registry updated: status → ACTIVE
        ↓
New doc is now queryable — org_name users
can ask questions about it immediately


## User DELETEs Question:
Admin deletes old_policy.pdf from S3. Users can no longer retrieve answers from it.

Admin deletes PDF from S3 console
        ↓
S3 fires ObjectRemoved event
        ↓
EventBridge rule matches
        ↓
sena-misty-cleanup Lambda invoked
        ↓
Lambda:
    1. Registry updated: status → DELETING
        ↓
    2. Deletes .metadata.json sidecar from S3
        ↓
    3. Calls start_ingestion_job(DELETE_NOT_FOUND)
        ↓
Bedrock KB scans every vector in index
    → Checks source S3 URI for each vector
    → Finds vectors from deleted file
    → Deletes those vectors + chunks
        ↓
Lambda polls until COMPLETE
        ↓
Registry updated: status → DELETED + deleted_at timestamp
        ↓
Doc is permanently removed from index
Users get NOT_IN_KB if they ask about it
## Architecture
┌─────────────┐     ┌──────────┐     ┌─────────────┐     ┌──────────────────┐
│  Streamlit  │────▶│  FastAPI │────▶│ API Gateway │────▶│  Query Lambda    │
│  (UI layer) │◀────│ (router) │◀────│  (HTTP API) │◀────│  pipeline.py     │
└─────────────┘     └──────────┘     └─────────────┘     └──────────────────┘
                                                                    │
                                              ┌─────────────────────┼──────────────────┐
                                              ▼                     ▼                  ▼
                                        Bedrock KB            DynamoDB           AgentCore
                                        S3 Vectors            Sessions           Memory
                                        (retrieval)           Turns              (long-term)

┌─────────────┐     ┌─────────────┐     ┌──────────────────┐
│  S3 Upload  │────▶│ EventBridge │────▶│ Ingestion Lambda │────▶ Bedrock KB sync
└─────────────┘     └─────────────┘     └──────────────────┘           │
                                                                         ▼
┌─────────────┐     ┌─────────────┐     ┌──────────────────┐      DynamoDB
│  S3 Delete  │────▶│ EventBridge │────▶│  Cleanup Lambda  │────▶  Registry
└─────────────┘     └─────────────┘     └──────────────────┘



## SENA RAG — Component Summary

| Component | Role | Purpose |
| **Streamlit** | Frontend | What the user sees and types into |
| **FastAPI** | Router | Receives from Streamlit, forwards to pipeline or Lambda |
| **API Gateway** | AWS front door | Receives HTTP requests, invokes query Lambda |
| **Query Lambda** | Pipeline runner | Runs the full RAG pipeline in AWS |
| **Ingestion Lambda** | Doc processor | Processes new docs automatically on S3 upload |
| **Cleanup Lambda** | Doc remover | Removes vectors automatically on S3 delete |
| **Bedrock KB** | Retrieval engine | Retrieves relevant chunks from S3 Vectors |
| **S3 Vectors** | Vector store | Stores all embeddings with org_id metadata |
| **S3** | Document store | Stores raw PDFs and DOCX files per org |
| **EventBridge** | Event router | Routes S3 upload/delete events to the right Lambda |
| **DynamoDB** | Persistence | Stores sessions, turns, and doc registry |
| **AgentCore Memory** | Long-term memory | Remembers user facts and preferences across sessions |
| **Titan V2** | Embedding model | Converts text chunks to 1024-dimension vectors |
| **Nova Micro** | Classifier + Reranker | Classifies intent, reranks retrieved chunks |
| **Nova Lite** | Query rewriter | Rewrites user query for better retrieval |
| **Claude Haiku 4.5** | Generator | Produces the final answer from retrieved context |
| **IAM** | Permissions | Controls which services can talk to each other |
| **CloudWatch** | Logging | Captures logs and metrics from all Lambdas | [Not implemented]
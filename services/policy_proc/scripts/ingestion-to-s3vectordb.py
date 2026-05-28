import boto3
import time

from config import REGION, KB_ID, DS_ID

bedrock_agent = boto3.client("bedrock-agent", region_name=REGION)

job = bedrock_agent.start_ingestion_job(
    knowledgeBaseId=KB_ID,
    dataSourceId=DS_ID
)

job_id = job["ingestionJob"]["ingestionJobId"]
print(f"Ingestion Job ID: {job_id}")

while True:
    response = bedrock_agent.get_ingestion_job(
        knowledgeBaseId=KB_ID,
        dataSourceId=DS_ID,
        ingestionJobId=job_id
    )["ingestionJob"]
    
    status = response["status"]
    print(f"Status: {status}")
    
    if status == "COMPLETE":
        print(f" Done! Documents indexed: {response.get('statistics', {}).get('numberOfNewDocumentsIndexed', 'N/A')}")
        break
    elif status == "FAILED":
        print(response.get("failureReasons"))
        raise Exception(" Ingestion failed")
    
    time.sleep(10)

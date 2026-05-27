import boto3
import time

bedrock_agent = boto3.client("bedrock-agent", region_name="ap-southeast-2")

KB_ID = "KFWSFMVU8U"
DS_ID = "CWJ8UCZSCY"

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
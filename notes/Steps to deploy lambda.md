1. python setup_dynamodb_registry.py     ← run this now (no Lambda dependency)

2. cd deployment_lambda
   python deploy_doc_lambdas.py          ← deploys both ingestion + cleanup Lambdas

3. Back in setup.ipynb:
   Run setup_eventbridge_upload cell     ← now Lambda exists, will succeed
   Run setup_eventbridge_delete cell     ← now Lambda exists, will succeed

4. cd deployment_lambda
   python deploy_query_lambda.py         ← deploys query handler Lambda
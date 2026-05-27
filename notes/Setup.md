## Current setup (local/QA)
Streamlit → FastAPI → pipeline.py (local)
                          ↓
                    All scripts run
                    on your machine


## Production setup (after API Gateway)
Streamlit/Client's Website → FastAPI → API Gateway → query Lambda
                                                        ↓
                                                All scripts run
                                                in AWS Lambda

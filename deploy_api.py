#!/usr/bin/env python3
"""
Deploy Profile Management API (Lambda + API Gateway).
"""

import json
import subprocess
import zipfile
import time
from pathlib import Path

REGION = "eu-north-1"
ACCOUNT_ID = "043760299039"
BUCKET_NAME = "job-scanner-dashboard-043760299039"
FUNCTION_NAME = "job-scanner-api"
SCANNER_FUNCTION = "job-scanner"
API_NAME = "job-scanner-api"
ROLE_NAME = "job-scanner-lambda-role"  # Reuse existing role
BASE_DIR = Path(__file__).parent


def run_aws(args):
    """Run AWS CLI command."""
    cmd = ["aws"] + args
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        if "already exists" not in result.stderr and "ResourceConflictException" not in result.stderr:
            print(f"  Warning: {result.stderr[:200]}")
        return None
    return result.stdout.strip()


def create_lambda():
    """Create the API Lambda function."""
    print("\n[1/5] Creating API Lambda function...")

    # Create zip
    zip_path = BASE_DIR / "lambda_api.zip"
    with zipfile.ZipFile(zip_path, 'w') as z:
        z.write(BASE_DIR / "lambda_api.py", "lambda_function.py")

    # Check if exists
    result = run_aws(["lambda", "get-function", "--function-name", FUNCTION_NAME])

    # Get role ARN
    role_result = run_aws([
        "iam", "get-role",
        "--role-name", ROLE_NAME,
        "--query", "Role.Arn",
        "--output", "text"
    ])
    role_arn = role_result or f"arn:aws:iam::{ACCOUNT_ID}:role/{ROLE_NAME}"

    env_vars = {"Variables": {"BUCKET_NAME": BUCKET_NAME, "SCANNER_FUNCTION": SCANNER_FUNCTION}}

    if result:
        print(f"  Updating existing function...")
        run_aws([
            "lambda", "update-function-code",
            "--function-name", FUNCTION_NAME,
            "--zip-file", f"fileb://{zip_path}"
        ])
        time.sleep(3)
        run_aws([
            "lambda", "update-function-configuration",
            "--function-name", FUNCTION_NAME,
            "--environment", json.dumps(env_vars)
        ])
    else:
        print(f"  Creating new function...")
        run_aws([
            "lambda", "create-function",
            "--function-name", FUNCTION_NAME,
            "--runtime", "python3.11",
            "--role", role_arn,
            "--handler", "lambda_function.lambda_handler",
            "--zip-file", f"fileb://{zip_path}",
            "--timeout", "30",
            "--memory-size", "128",
            "--environment", json.dumps(env_vars)
        ])

    zip_path.unlink()
    print(f"  Function ready: {FUNCTION_NAME}")
    return True


def create_api_gateway():
    """Create HTTP API Gateway."""
    print("\n[2/5] Creating API Gateway...")

    # Check if API exists
    result = run_aws([
        "apigatewayv2", "get-apis",
        "--query", f"Items[?Name=='{API_NAME}'].ApiId",
        "--output", "text"
    ])

    if result:
        api_id = result.split()[0] if result else None
        if api_id:
            print(f"  API already exists: {api_id}")
            return api_id

    # Create HTTP API
    result = run_aws([
        "apigatewayv2", "create-api",
        "--name", API_NAME,
        "--protocol-type", "HTTP",
        "--cors-configuration", json.dumps({
            "AllowOrigins": ["*"],
            "AllowMethods": ["GET", "PUT", "POST", "OPTIONS"],
            "AllowHeaders": ["Content-Type", "Authorization"]
        }),
        "--query", "ApiId",
        "--output", "text"
    ])

    api_id = result
    print(f"  Created API: {api_id}")
    return api_id


def setup_integration(api_id):
    """Set up Lambda integration."""
    print("\n[3/5] Setting up Lambda integration...")

    lambda_arn = f"arn:aws:lambda:{REGION}:{ACCOUNT_ID}:function:{FUNCTION_NAME}"

    # Create integration
    result = run_aws([
        "apigatewayv2", "get-integrations",
        "--api-id", api_id,
        "--query", "Items[0].IntegrationId",
        "--output", "text"
    ])

    if result and result != "None":
        integration_id = result
        print(f"  Integration exists: {integration_id}")
    else:
        result = run_aws([
            "apigatewayv2", "create-integration",
            "--api-id", api_id,
            "--integration-type", "AWS_PROXY",
            "--integration-uri", lambda_arn,
            "--payload-format-version", "2.0",
            "--query", "IntegrationId",
            "--output", "text"
        ])
        integration_id = result
        print(f"  Created integration: {integration_id}")

    # Create routes for /profiles
    for method in ["GET", "PUT", "OPTIONS"]:
        run_aws([
            "apigatewayv2", "create-route",
            "--api-id", api_id,
            "--route-key", f"{method} /profiles",
            "--target", f"integrations/{integration_id}"
        ])

    # Create route for /run
    for method in ["POST", "OPTIONS"]:
        run_aws([
            "apigatewayv2", "create-route",
            "--api-id", api_id,
            "--route-key", f"{method} /run",
            "--target", f"integrations/{integration_id}"
        ])

    # Create routes for /notifications
    for method in ["GET", "OPTIONS"]:
        run_aws([
            "apigatewayv2", "create-route",
            "--api-id", api_id,
            "--route-key", f"{method} /notifications",
            "--target", f"integrations/{integration_id}"
        ])

    # Create route for /notifications/read-all
    for method in ["PUT", "OPTIONS"]:
        run_aws([
            "apigatewayv2", "create-route",
            "--api-id", api_id,
            "--route-key", f"{method} /notifications/read-all",
            "--target", f"integrations/{integration_id}"
        ])

    # Create route for /notifications/{id}/read (using proxy for path param)
    for method in ["PUT", "OPTIONS"]:
        run_aws([
            "apigatewayv2", "create-route",
            "--api-id", api_id,
            "--route-key", f"{method} /notifications/{{id}}/read",
            "--target", f"integrations/{integration_id}"
        ])

    # Add Lambda permission
    run_aws([
        "lambda", "add-permission",
        "--function-name", FUNCTION_NAME,
        "--statement-id", f"apigateway-{api_id}",
        "--action", "lambda:InvokeFunction",
        "--principal", "apigateway.amazonaws.com",
        "--source-arn", f"arn:aws:execute-api:{REGION}:{ACCOUNT_ID}:{api_id}/*"
    ])

    # Create/update stage
    run_aws([
        "apigatewayv2", "create-stage",
        "--api-id", api_id,
        "--stage-name", "$default",
        "--auto-deploy"
    ])

    print("  Routes configured")
    return integration_id


def add_invoke_permission():
    """Add permission for API Lambda to invoke scanner Lambda."""
    print("\n[4/5] Adding Lambda invoke permission...")

    policy_name = f"{FUNCTION_NAME}-invoke-policy"
    policy_doc = {
        "Version": "2012-10-17",
        "Statement": [{
            "Effect": "Allow",
            "Action": "lambda:InvokeFunction",
            "Resource": f"arn:aws:lambda:{REGION}:{ACCOUNT_ID}:function:{SCANNER_FUNCTION}"
        }]
    }

    # Check if policy exists
    existing = run_aws([
        "iam", "list-policies",
        "--query", f"Policies[?PolicyName=='{policy_name}'].Arn",
        "--output", "text"
    ])

    if existing:
        policy_arn = existing
        print(f"  Policy exists: {policy_name}")
    else:
        result = run_aws([
            "iam", "create-policy",
            "--policy-name", policy_name,
            "--policy-document", json.dumps(policy_doc),
            "--query", "Policy.Arn",
            "--output", "text"
        ])
        policy_arn = result
        print(f"  Created policy: {policy_name}")

    if policy_arn:
        run_aws([
            "iam", "attach-role-policy",
            "--role-name", ROLE_NAME,
            "--policy-arn", policy_arn
        ])
        print("  Policy attached to role")


def get_api_url(api_id):
    """Get the API endpoint URL."""
    print("\n[5/5] Getting API endpoint...")

    result = run_aws([
        "apigatewayv2", "get-api",
        "--api-id", api_id,
        "--query", "ApiEndpoint",
        "--output", "text"
    ])

    api_url = result
    print(f"  API URL: {api_url}")
    return api_url


def update_dashboard(api_url):
    """Update the static dashboard with the API URL."""
    print("\nUpdating dashboard configuration...")

    # Save API URL to S3 for dashboard to use
    config = {"apiUrl": api_url}

    subprocess.run([
        "aws", "s3", "cp", "-",
        f"s3://{BUCKET_NAME}/data/api_config.json",
        "--content-type", "application/json"
    ], input=json.dumps(config), text=True)

    print("  Dashboard config updated")


def main():
    print("=" * 60)
    print("Job Scanner - API Deployment")
    print("=" * 60)

    create_lambda()
    api_id = create_api_gateway()
    setup_integration(api_id)
    add_invoke_permission()
    api_url = get_api_url(api_id)
    update_dashboard(api_url)

    print("\n" + "=" * 60)
    print("API Deployment complete!")
    print("=" * 60)
    print(f"""
API Endpoints:
  {api_url}/profiles
    GET  - Retrieve all profiles
    PUT  - Save profiles

  {api_url}/run
    POST - Trigger scanner manually

  {api_url}/notifications
    GET  - Get notifications (unread first)

  {api_url}/notifications/read-all
    PUT  - Mark all notifications as read

  {api_url}/notifications/{{id}}/read
    PUT  - Mark single notification as read

Test with:
  curl {api_url}/profiles
  curl -X POST {api_url}/run
  curl {api_url}/notifications
""")


if __name__ == "__main__":
    main()

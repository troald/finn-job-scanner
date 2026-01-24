#!/usr/bin/env python3
"""
Deploy Job Scanner as AWS Lambda function with scheduled execution.
"""

import json
import subprocess
import sys
import time
import zipfile
import os
import tempfile
import shutil
from pathlib import Path

# Configuration
BUCKET_NAME = "job-scanner-dashboard-043760299039"
REGION = "eu-north-1"
ACCOUNT_ID = "043760299039"
FUNCTION_NAME = "job-scanner"
ROLE_NAME = "job-scanner-lambda-role"
SECRET_NAME = "job-scanner/anthropic-api-key"
RULE_NAME = "job-scanner-daily"
BASE_DIR = Path(__file__).parent


def run_aws(args, capture=True):
    """Run AWS CLI command."""
    cmd = ["aws"] + args
    if capture:
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0 and "already exists" not in result.stderr:
            print(f"Warning: {result.stderr}")
        return result.stdout.strip() if result.returncode == 0 else None
    else:
        subprocess.run(cmd)
        return None


def create_iam_role():
    """Create IAM role for Lambda."""
    print("\n[1/6] Creating IAM role for Lambda...")

    # Check if role exists
    result = run_aws(["iam", "get-role", "--role-name", ROLE_NAME])
    if result:
        print(f"  Role already exists: {ROLE_NAME}")
        role_arn = json.loads(result)['Role']['Arn']
        return role_arn

    # Trust policy for Lambda
    trust_policy = {
        "Version": "2012-10-17",
        "Statement": [{
            "Effect": "Allow",
            "Principal": {"Service": "lambda.amazonaws.com"},
            "Action": "sts:AssumeRole"
        }]
    }

    # Create role
    result = run_aws([
        "iam", "create-role",
        "--role-name", ROLE_NAME,
        "--assume-role-policy-document", json.dumps(trust_policy),
        "--query", "Role.Arn",
        "--output", "text"
    ])

    if not result:
        print("  Error creating role")
        return None

    role_arn = result
    print(f"  Created role: {role_arn}")

    # Attach basic Lambda execution policy
    run_aws([
        "iam", "attach-role-policy",
        "--role-name", ROLE_NAME,
        "--policy-arn", "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
    ])

    # Create and attach S3/Secrets policy
    policy_name = f"{ROLE_NAME}-policy"
    policy_doc = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Action": [
                    "s3:GetObject",
                    "s3:PutObject",
                    "s3:ListBucket"
                ],
                "Resource": [
                    f"arn:aws:s3:::{BUCKET_NAME}",
                    f"arn:aws:s3:::{BUCKET_NAME}/*"
                ]
            },
            {
                "Effect": "Allow",
                "Action": [
                    "secretsmanager:GetSecretValue"
                ],
                "Resource": [
                    f"arn:aws:secretsmanager:{REGION}:{ACCOUNT_ID}:secret:{SECRET_NAME}*"
                ]
            }
        ]
    }

    # Check if policy exists
    existing = run_aws([
        "iam", "list-policies",
        "--query", f"Policies[?PolicyName=='{policy_name}'].Arn",
        "--output", "text"
    ])

    if existing:
        policy_arn = existing
    else:
        result = run_aws([
            "iam", "create-policy",
            "--policy-name", policy_name,
            "--policy-document", json.dumps(policy_doc),
            "--query", "Policy.Arn",
            "--output", "text"
        ])
        policy_arn = result

    if policy_arn:
        run_aws([
            "iam", "attach-role-policy",
            "--role-name", ROLE_NAME,
            "--policy-arn", policy_arn
        ])

    print("  Attached policies")

    # Wait for role to propagate
    time.sleep(10)

    return role_arn


def store_api_key():
    """Store Anthropic API key in Secrets Manager."""
    print("\n[2/6] Setting up API key in Secrets Manager...")

    # Check if secret exists
    result = run_aws([
        "secretsmanager", "describe-secret",
        "--secret-id", SECRET_NAME
    ])

    if result:
        print(f"  Secret already exists: {SECRET_NAME}")
        print("  To update the API key, run:")
        print(f"    aws secretsmanager put-secret-value --secret-id {SECRET_NAME} --secret-string '{{\"ANTHROPIC_API_KEY\":\"your-key\"}}'")
        return True

    # Get API key from user or environment
    api_key = os.environ.get('ANTHROPIC_API_KEY', '')

    if not api_key:
        print("\n  ANTHROPIC_API_KEY not found in environment.")
        print("  Please enter your Anthropic API key (or press Enter to skip and set it later):")
        api_key = input("  API Key: ").strip()

    if api_key:
        secret_value = json.dumps({"ANTHROPIC_API_KEY": api_key})
        run_aws([
            "secretsmanager", "create-secret",
            "--name", SECRET_NAME,
            "--description", "Anthropic API key for Job Scanner",
            "--secret-string", secret_value
        ])
        print(f"  Created secret: {SECRET_NAME}")
    else:
        print("  Skipping secret creation. Create it manually:")
        print(f"    aws secretsmanager create-secret --name {SECRET_NAME} --secret-string '{{\"ANTHROPIC_API_KEY\":\"your-key\"}}'")

    return True


def upload_config():
    """Upload search profiles configuration to S3 (only if none exists)."""
    print("\n[3/6] Checking search profiles configuration...")

    # Check if config already exists in S3
    existing = run_aws([
        "s3", "ls",
        f"s3://{BUCKET_NAME}/config/search_profiles.json"
    ])

    if existing:
        print("  Config already exists in S3 (managed via web UI)")
        print("  Skipping upload to preserve web UI changes")
        return True

    # No config in S3 - upload from local config.py (first-time setup)
    print("  No config in S3, uploading from config.py...")

    config_file = BASE_DIR / "config.py"
    config_globals = {}
    exec(open(config_file).read(), config_globals)
    search_profiles = config_globals.get('SEARCH_PROFILES', {})

    if not search_profiles:
        print("  Warning: No SEARCH_PROFILES found in config.py")
        return False

    config_path = BASE_DIR / "search_profiles_temp.json"
    with open(config_path, 'w') as f:
        json.dump(search_profiles, f, indent=2)

    run_aws([
        "s3", "cp",
        str(config_path),
        f"s3://{BUCKET_NAME}/config/search_profiles.json",
        "--content-type", "application/json"
    ])

    config_path.unlink()
    print("  Uploaded initial search profiles to S3")
    return True


def create_lambda_package():
    """Create Lambda deployment package with dependencies using Docker."""
    print("\n[4/6] Creating Lambda deployment package...")

    zip_path = BASE_DIR / "lambda_package.zip"

    # Check if Docker is available
    try:
        docker_check = subprocess.run(["docker", "info"], capture_output=True)
        use_docker = docker_check.returncode == 0
    except FileNotFoundError:
        use_docker = False

    if use_docker:
        print("  Using Docker for Linux-compatible dependencies...")

        # Create temp directory for Docker build
        temp_dir = tempfile.mkdtemp()
        package_dir = Path(temp_dir) / "package"
        package_dir.mkdir()

        try:
            # Copy lambda function to temp dir
            shutil.copy(BASE_DIR / "lambda_function.py", temp_dir)

            # Create requirements file
            requirements = temp_dir + "/requirements.txt"
            with open(requirements, 'w') as f:
                f.write("anthropic\nrequests\nbeautifulsoup4\n")

            # Run pip install inside Docker container with Lambda Python runtime
            print("  Installing dependencies in Docker container...")
            subprocess.run([
                "docker", "run", "--rm",
                "-v", f"{temp_dir}:/var/task",
                "public.ecr.aws/lambda/python:3.11",
                "pip", "install", "-r", "/var/task/requirements.txt",
                "-t", "/var/task/package", "--quiet"
            ], check=True)

            # Copy lambda function to package
            shutil.copy(temp_dir + "/lambda_function.py", str(package_dir) + "/lambda_function.py")

            # Create zip file
            print(f"  Creating {zip_path}...")
            with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                for root, dirs, files in os.walk(package_dir):
                    for file in files:
                        file_path = Path(root) / file
                        arcname = file_path.relative_to(package_dir)
                        zipf.write(file_path, arcname)

            print(f"  Package created: {zip_path.stat().st_size / 1024 / 1024:.1f} MB")
            return zip_path

        finally:
            shutil.rmtree(temp_dir)
    else:
        print("  Docker not available, using pip with Linux platform targeting...")

        # Use pip with platform targeting to get Linux wheels
        temp_dir = tempfile.mkdtemp()
        package_dir = Path(temp_dir) / "package"
        package_dir.mkdir()

        try:
            # Install with Linux platform targeting
            subprocess.run([
                sys.executable, "-m", "pip", "install",
                "anthropic", "requests", "beautifulsoup4",
                "-t", str(package_dir),
                "--platform", "manylinux2014_x86_64",
                "--implementation", "cp",
                "--python-version", "3.11",
                "--only-binary=:all:",
                "--quiet"
            ], check=True)

            shutil.copy(BASE_DIR / "lambda_function.py", package_dir / "lambda_function.py")

            with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                for root, dirs, files in os.walk(package_dir):
                    for file in files:
                        file_path = Path(root) / file
                        arcname = file_path.relative_to(package_dir)
                        zipf.write(file_path, arcname)

            print(f"  Package created: {zip_path.stat().st_size / 1024 / 1024:.1f} MB")
            return zip_path

        finally:
            shutil.rmtree(temp_dir)


def create_lambda_function(role_arn, zip_path):
    """Create or update Lambda function."""
    print("\n[5/6] Creating Lambda function...")

    # Check if function exists
    result = run_aws([
        "lambda", "get-function",
        "--function-name", FUNCTION_NAME
    ])

    env_vars = {
        "Variables": {
            "BUCKET_NAME": BUCKET_NAME,
            "SECRET_NAME": SECRET_NAME
        }
    }

    if result:
        print(f"  Updating existing function: {FUNCTION_NAME}")
        # Update code
        run_aws([
            "lambda", "update-function-code",
            "--function-name", FUNCTION_NAME,
            "--zip-file", f"fileb://{zip_path}"
        ])
        time.sleep(5)
        # Update configuration
        run_aws([
            "lambda", "update-function-configuration",
            "--function-name", FUNCTION_NAME,
            "--timeout", "900",
            "--memory-size", "512",
            "--environment", json.dumps(env_vars)
        ])
    else:
        print(f"  Creating new function: {FUNCTION_NAME}")
        run_aws([
            "lambda", "create-function",
            "--function-name", FUNCTION_NAME,
            "--runtime", "python3.11",
            "--role", role_arn,
            "--handler", "lambda_function.lambda_handler",
            "--zip-file", f"fileb://{zip_path}",
            "--timeout", "900",
            "--memory-size", "512",
            "--environment", json.dumps(env_vars)
        ])

    print(f"  Function ready: {FUNCTION_NAME}")

    # Clean up zip file
    zip_path.unlink()

    return True


def create_schedule():
    """Create EventBridge rule to run Lambda daily."""
    print("\n[6/6] Creating daily schedule...")

    # Create rule (8 AM UTC, adjust as needed)
    run_aws([
        "events", "put-rule",
        "--name", RULE_NAME,
        "--schedule-expression", "cron(0 7 * * ? *)",  # 7 AM UTC = 8 AM CET
        "--state", "ENABLED",
        "--description", "Run job scanner daily at 8 AM CET"
    ])

    # Get Lambda ARN
    result = run_aws([
        "lambda", "get-function",
        "--function-name", FUNCTION_NAME,
        "--query", "Configuration.FunctionArn",
        "--output", "text"
    ])

    if result:
        function_arn = result

        # Add permission for EventBridge to invoke Lambda
        run_aws([
            "lambda", "add-permission",
            "--function-name", FUNCTION_NAME,
            "--statement-id", "EventBridgeInvoke",
            "--action", "lambda:InvokeFunction",
            "--principal", "events.amazonaws.com",
            "--source-arn", f"arn:aws:events:{REGION}:{ACCOUNT_ID}:rule/{RULE_NAME}"
        ])

        # Add target
        targets = [{
            "Id": "JobScannerTarget",
            "Arn": function_arn
        }]

        run_aws([
            "events", "put-targets",
            "--rule", RULE_NAME,
            "--targets", json.dumps(targets)
        ])

        print(f"  Schedule created: {RULE_NAME}")
        print("  Runs daily at 8:00 AM CET (7:00 AM UTC)")

    return True


def test_lambda():
    """Test the Lambda function."""
    print("\n" + "=" * 60)
    print("Testing Lambda function...")
    print("=" * 60)

    result = subprocess.run([
        "aws", "lambda", "invoke",
        "--function-name", FUNCTION_NAME,
        "--log-type", "Tail",
        "--query", "LogResult",
        "--output", "text",
        "/dev/stdout"
    ], capture_output=True, text=True)

    if result.returncode == 0:
        # Decode base64 logs
        import base64
        try:
            logs = base64.b64decode(result.stdout).decode('utf-8')
            print("\nLambda logs (last 4KB):")
            print(logs[-4000:] if len(logs) > 4000 else logs)
        except:
            print(result.stdout)
    else:
        print(f"Error: {result.stderr}")


def main():
    print("=" * 60)
    print("Job Scanner - AWS Lambda Deployment")
    print("=" * 60)

    # Step 1: Create IAM role
    role_arn = create_iam_role()
    if not role_arn:
        print("Failed to create IAM role")
        return

    # Step 2: Store API key
    store_api_key()

    # Step 3: Upload config
    upload_config()

    # Step 4: Create deployment package
    zip_path = create_lambda_package()

    # Step 5: Create/update Lambda function
    create_lambda_function(role_arn, zip_path)

    # Step 6: Create schedule
    create_schedule()

    print("\n" + "=" * 60)
    print("Deployment complete!")
    print("=" * 60)
    print(f"""
Lambda function: {FUNCTION_NAME}
Schedule: Daily at 8:00 AM CET
Dashboard: https://d28s0rx87qwx1z.cloudfront.net

To test manually:
  aws lambda invoke --function-name {FUNCTION_NAME} /dev/stdout

To view logs:
  aws logs tail /aws/lambda/{FUNCTION_NAME} --follow

To update search profiles:
  Edit config.py and run: python deploy_lambda.py

To update API key:
  aws secretsmanager put-secret-value --secret-id {SECRET_NAME} --secret-string '{{"ANTHROPIC_API_KEY":"your-key"}}'
""")

    # Ask if user wants to test
    print("\nWould you like to test the Lambda function now? (y/n)")
    choice = input().strip().lower()
    if choice == 'y':
        test_lambda()


if __name__ == "__main__":
    main()

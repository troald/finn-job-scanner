#!/usr/bin/env python3
"""
Deploy Job Scanner Dashboard to AWS CloudFront with password protection.
Creates S3 bucket, CloudFront distribution with basic auth.
"""

import json
import subprocess
import sys
import time
import secrets
import string
import base64
from pathlib import Path

# Configuration
BUCKET_NAME = "job-scanner-dashboard-043760299039"
REGION = "eu-north-1"
BASE_DIR = Path(__file__).parent


def run_aws(args, capture=True):
    """Run AWS CLI command."""
    cmd = ["aws"] + args
    if capture:
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            print(f"Error: {result.stderr}")
            return None
        return result.stdout.strip()
    else:
        subprocess.run(cmd)


def generate_password(length=16):
    """Generate a secure random password."""
    chars = string.ascii_letters + string.digits
    return ''.join(secrets.choice(chars) for _ in range(length))


def create_bucket():
    """Create S3 bucket if it doesn't exist."""
    print(f"\n[1/5] Creating S3 bucket: {BUCKET_NAME}")

    # Check if bucket exists
    result = run_aws(["s3api", "head-bucket", "--bucket", BUCKET_NAME])
    if result is not None:
        print(f"  Bucket already exists")
        return True

    # Create bucket with location constraint for non-us-east-1 regions
    if REGION == "us-east-1":
        run_aws([
            "s3api", "create-bucket",
            "--bucket", BUCKET_NAME,
            "--region", REGION
        ])
    else:
        run_aws([
            "s3api", "create-bucket",
            "--bucket", BUCKET_NAME,
            "--region", REGION,
            "--create-bucket-configuration", f"LocationConstraint={REGION}"
        ])

    # Block public access (CloudFront will access via OAC)
    run_aws([
        "s3api", "put-public-access-block",
        "--bucket", BUCKET_NAME,
        "--public-access-block-configuration",
        "BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true"
    ])

    print(f"  Bucket created successfully")
    return True


def create_cloudfront_function(username, password):
    """Create CloudFront Function for basic auth."""
    print(f"\n[2/5] Creating CloudFront Function for authentication")

    function_name = "job-scanner-basic-auth"

    # Check if function already exists
    result = run_aws([
        "cloudfront", "list-functions",
        "--query", f"FunctionList.Items[?Name=='{function_name}'].Name",
        "--output", "text"
    ])

    # Base64 encode credentials for comparison
    credentials = base64.b64encode(f"{username}:{password}".encode()).decode()

    function_code = f'''function handler(event) {{
    var request = event.request;
    var headers = request.headers;
    var authString = "Basic {credentials}";

    if (
        typeof headers.authorization === "undefined" ||
        headers.authorization.value !== authString
    ) {{
        return {{
            statusCode: 401,
            statusDescription: "Unauthorized",
            headers: {{
                "www-authenticate": {{ value: "Basic realm=\\"Job Scanner Dashboard\\"" }}
            }}
        }};
    }}

    return request;
}}'''

    # Write function code to temp file
    func_file = BASE_DIR / "cf_function.js"
    func_file.write_text(function_code)

    if result and function_name in result:
        print(f"  Function exists, updating...")
        # Get current etag
        desc = run_aws([
            "cloudfront", "describe-function",
            "--name", function_name,
            "--query", "ETag",
            "--output", "text"
        ])

        run_aws([
            "cloudfront", "update-function",
            "--name", function_name,
            "--function-config", "Comment=Basic auth for job scanner,Runtime=cloudfront-js-2.0",
            "--function-code", f"fileb://{func_file}",
            "--if-match", desc
        ])

        # Get new etag and publish
        desc = run_aws([
            "cloudfront", "describe-function",
            "--name", function_name,
            "--query", "ETag",
            "--output", "text"
        ])

        run_aws([
            "cloudfront", "publish-function",
            "--name", function_name,
            "--if-match", desc
        ])
    else:
        print(f"  Creating new function...")
        run_aws([
            "cloudfront", "create-function",
            "--name", function_name,
            "--function-config", "Comment=Basic auth for job scanner,Runtime=cloudfront-js-2.0",
            "--function-code", f"fileb://{func_file}"
        ])

        # Get etag and publish
        desc = run_aws([
            "cloudfront", "describe-function",
            "--name", function_name,
            "--query", "ETag",
            "--output", "text"
        ])

        run_aws([
            "cloudfront", "publish-function",
            "--name", function_name,
            "--if-match", desc
        ])

    # Clean up temp file
    func_file.unlink()

    # Get function ARN
    result = run_aws([
        "cloudfront", "describe-function",
        "--name", function_name,
        "--query", "FunctionSummary.FunctionMetadata.FunctionARN",
        "--output", "text"
    ])

    print(f"  Function ready: {function_name}")
    return result


def create_oac():
    """Create Origin Access Control for S3."""
    print(f"\n[3/5] Creating Origin Access Control")

    oac_name = "job-scanner-oac"

    # Check if OAC exists
    result = run_aws([
        "cloudfront", "list-origin-access-controls",
        "--query", f"OriginAccessControlList.Items[?Name=='{oac_name}'].Id",
        "--output", "text"
    ])

    if result:
        print(f"  OAC already exists: {result}")
        return result

    # Create OAC
    oac_config = {
        "Name": oac_name,
        "Description": "OAC for job scanner dashboard",
        "SigningProtocol": "sigv4",
        "SigningBehavior": "always",
        "OriginAccessControlOriginType": "s3"
    }

    result = run_aws([
        "cloudfront", "create-origin-access-control",
        "--origin-access-control-config", json.dumps(oac_config),
        "--query", "OriginAccessControl.Id",
        "--output", "text"
    ])

    print(f"  OAC created: {result}")
    return result


def create_cloudfront_distribution(function_arn, oac_id):
    """Create CloudFront distribution."""
    print(f"\n[4/5] Creating CloudFront distribution")

    # Check if distribution already exists
    result = run_aws([
        "cloudfront", "list-distributions",
        "--query", f"DistributionList.Items[?Comment=='Job Scanner Dashboard'].Id",
        "--output", "text"
    ])

    if result:
        print(f"  Distribution already exists: {result}")
        # Get domain name
        domain = run_aws([
            "cloudfront", "get-distribution",
            "--id", result,
            "--query", "Distribution.DomainName",
            "--output", "text"
        ])
        return result, domain

    # Distribution configuration
    dist_config = {
        "CallerReference": f"job-scanner-{int(time.time())}",
        "Comment": "Job Scanner Dashboard",
        "Enabled": True,
        "DefaultRootObject": "index.html",
        "Origins": {
            "Quantity": 1,
            "Items": [{
                "Id": "S3Origin",
                "DomainName": f"{BUCKET_NAME}.s3.{REGION}.amazonaws.com",
                "S3OriginConfig": {
                    "OriginAccessIdentity": ""
                },
                "OriginAccessControlId": oac_id
            }]
        },
        "DefaultCacheBehavior": {
            "TargetOriginId": "S3Origin",
            "ViewerProtocolPolicy": "redirect-to-https",
            "AllowedMethods": {
                "Quantity": 2,
                "Items": ["GET", "HEAD"],
                "CachedMethods": {
                    "Quantity": 2,
                    "Items": ["GET", "HEAD"]
                }
            },
            "CachePolicyId": "658327ea-f89d-4fab-a63d-7e88639e58f6",  # CachingOptimized
            "Compress": True,
            "FunctionAssociations": {
                "Quantity": 1,
                "Items": [{
                    "FunctionARN": function_arn,
                    "EventType": "viewer-request"
                }]
            }
        },
        "CustomErrorResponses": {
            "Quantity": 1,
            "Items": [{
                "ErrorCode": 403,
                "ResponsePagePath": "/index.html",
                "ResponseCode": "200",
                "ErrorCachingMinTTL": 10
            }]
        },
        "PriceClass": "PriceClass_100",
        "ViewerCertificate": {
            "CloudFrontDefaultCertificate": True
        }
    }

    result = run_aws([
        "cloudfront", "create-distribution",
        "--distribution-config", json.dumps(dist_config),
        "--query", "[Distribution.Id, Distribution.DomainName]",
        "--output", "text"
    ])

    dist_id, domain = result.split()

    # Add bucket policy to allow CloudFront access
    bucket_policy = {
        "Version": "2012-10-17",
        "Statement": [{
            "Sid": "AllowCloudFrontServicePrincipal",
            "Effect": "Allow",
            "Principal": {
                "Service": "cloudfront.amazonaws.com"
            },
            "Action": "s3:GetObject",
            "Resource": f"arn:aws:s3:::{BUCKET_NAME}/*",
            "Condition": {
                "StringEquals": {
                    "AWS:SourceArn": f"arn:aws:cloudfront::043760299039:distribution/{dist_id}"
                }
            }
        }]
    }

    run_aws([
        "s3api", "put-bucket-policy",
        "--bucket", BUCKET_NAME,
        "--policy", json.dumps(bucket_policy)
    ])

    print(f"  Distribution created: {dist_id}")
    print(f"  Domain: {domain}")
    return dist_id, domain


def upload_static_files():
    """Upload static files to S3."""
    print(f"\n[5/5] Uploading static files")

    static_dir = BASE_DIR / "static"

    # Upload index.html
    run_aws([
        "s3", "cp",
        str(static_dir / "index.html"),
        f"s3://{BUCKET_NAME}/index.html",
        "--content-type", "text/html"
    ])
    print(f"  Uploaded index.html")

    # Create data directory structure
    run_aws([
        "s3api", "put-object",
        "--bucket", BUCKET_NAME,
        "--key", "data/"
    ])

    run_aws([
        "s3api", "put-object",
        "--bucket", BUCKET_NAME,
        "--key", "data/reports/"
    ])

    # Upload initial empty data files
    empty_jobs = "{}"
    run_aws([
        "s3", "cp", "-",
        f"s3://{BUCKET_NAME}/data/analyzed_jobs.json",
        "--content-type", "application/json"
    ], capture=False)

    # Create empty reports index
    subprocess.run(
        ["aws", "s3", "cp", "-", f"s3://{BUCKET_NAME}/data/reports_index.json", "--content-type", "application/json"],
        input="[]",
        text=True
    )

    print(f"  Created data directory structure")


def save_config(domain, username, password, dist_id):
    """Save deployment configuration."""
    config = {
        "cloudfront_domain": domain,
        "cloudfront_url": f"https://{domain}",
        "distribution_id": dist_id,
        "bucket_name": BUCKET_NAME,
        "region": REGION,
        "username": username,
        "password": password
    }

    config_file = BASE_DIR / "aws_dashboard_config.json"
    config_file.write_text(json.dumps(config, indent=2))
    print(f"\nConfiguration saved to: {config_file}")


def main():
    print("=" * 60)
    print("Job Scanner Dashboard - AWS Deployment")
    print("=" * 60)

    # Generate credentials
    username = "admin"
    password = generate_password()

    print(f"\nGenerated credentials:")
    print(f"  Username: {username}")
    print(f"  Password: {password}")
    print(f"\n  (Save these - you'll need them to access the dashboard)")

    # Deploy infrastructure
    create_bucket()
    function_arn = create_cloudfront_function(username, password)
    oac_id = create_oac()
    dist_id, domain = create_cloudfront_distribution(function_arn, oac_id)
    upload_static_files()

    # Save config
    save_config(domain, username, password, dist_id)

    print("\n" + "=" * 60)
    print("Deployment complete!")
    print("=" * 60)
    print(f"\nDashboard URL: https://{domain}")
    print(f"Username: {username}")
    print(f"Password: {password}")
    print(f"\nNote: CloudFront may take 5-10 minutes to fully deploy.")
    print("The job scanner will now automatically upload data after each run.")


if __name__ == "__main__":
    main()

"""
AWS Lambda API handler for managing job scanner profiles.
Provides GET/PUT endpoints for search profiles configuration.
Also supports POST /run to trigger the scanner manually.
"""

import json
import boto3
import os

s3 = boto3.client('s3')
lambda_client = boto3.client('lambda')
BUCKET_NAME = os.environ.get('BUCKET_NAME', 'job-scanner-dashboard-043760299039')
SCANNER_FUNCTION = os.environ.get('SCANNER_FUNCTION', 'job-scanner')
CONFIG_KEY = 'config/search_profiles.json'


def lambda_handler(event, context):
    """Handle API Gateway requests."""

    # CORS headers
    headers = {
        'Content-Type': 'application/json',
        'Access-Control-Allow-Origin': '*',
        'Access-Control-Allow-Methods': 'GET, PUT, POST, OPTIONS',
        'Access-Control-Allow-Headers': 'Content-Type, Authorization'
    }

    # Handle preflight
    http_method = event.get('httpMethod') or event.get('requestContext', {}).get('http', {}).get('method', 'GET')
    path = event.get('path') or event.get('rawPath', '/profiles')

    if http_method == 'OPTIONS':
        return {
            'statusCode': 200,
            'headers': headers,
            'body': ''
        }

    try:
        # Route: POST /run - trigger scanner
        if http_method == 'POST' and '/run' in path:
            return trigger_scanner(headers)
        # Route: GET /profiles
        elif http_method == 'GET':
            return get_profiles(headers)
        # Route: PUT /profiles
        elif http_method == 'PUT':
            body = event.get('body', '{}')
            if isinstance(body, str):
                body = json.loads(body)
            return put_profiles(body, headers)
        else:
            return {
                'statusCode': 405,
                'headers': headers,
                'body': json.dumps({'error': 'Method not allowed'})
            }
    except Exception as e:
        return {
            'statusCode': 500,
            'headers': headers,
            'body': json.dumps({'error': str(e)})
        }


def get_profiles(headers):
    """Get all search profiles."""
    try:
        response = s3.get_object(Bucket=BUCKET_NAME, Key=CONFIG_KEY)
        profiles = json.loads(response['Body'].read().decode('utf-8'))
        return {
            'statusCode': 200,
            'headers': headers,
            'body': json.dumps(profiles)
        }
    except s3.exceptions.NoSuchKey:
        return {
            'statusCode': 200,
            'headers': headers,
            'body': json.dumps({})
        }


def put_profiles(profiles, headers):
    """Save search profiles."""
    # Validate structure
    if not isinstance(profiles, dict):
        return {
            'statusCode': 400,
            'headers': headers,
            'body': json.dumps({'error': 'Invalid profiles format'})
        }

    # Save to S3
    s3.put_object(
        Bucket=BUCKET_NAME,
        Key=CONFIG_KEY,
        Body=json.dumps(profiles, indent=2, ensure_ascii=False),
        ContentType='application/json'
    )

    # Also update the dashboard profiles metadata
    profiles_meta = {
        pid: {"name": p.get("name", pid), "enabled": p.get("enabled", True)}
        for pid, p in profiles.items()
    }
    s3.put_object(
        Bucket=BUCKET_NAME,
        Key='data/profiles.json',
        Body=json.dumps(profiles_meta, indent=2),
        ContentType='application/json'
    )

    return {
        'statusCode': 200,
        'headers': headers,
        'body': json.dumps({'message': 'Profiles saved successfully'})
    }


def trigger_scanner(headers):
    """Trigger the job scanner Lambda function asynchronously."""
    try:
        response = lambda_client.invoke(
            FunctionName=SCANNER_FUNCTION,
            InvocationType='Event',  # Async invocation
            Payload=json.dumps({'source': 'manual'})
        )

        status_code = response.get('StatusCode', 500)

        if status_code == 202:  # Accepted for async
            return {
                'statusCode': 200,
                'headers': headers,
                'body': json.dumps({
                    'message': 'Scanner started successfully',
                    'status': 'running'
                })
            }
        else:
            return {
                'statusCode': 500,
                'headers': headers,
                'body': json.dumps({'error': f'Failed to start scanner: {status_code}'})
            }
    except Exception as e:
        return {
            'statusCode': 500,
            'headers': headers,
            'body': json.dumps({'error': f'Failed to invoke scanner: {str(e)}'})
        }

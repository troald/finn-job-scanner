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
        # Route: GET /notifications
        elif http_method == 'GET' and '/notifications' in path:
            return get_notifications(headers)
        # Route: PUT /notifications/read-all
        elif http_method == 'PUT' and '/notifications/read-all' in path:
            return mark_all_notifications_read(headers)
        # Route: PUT /notifications/{id}/read
        elif http_method == 'PUT' and '/notifications/' in path and '/read' in path:
            # Extract notification ID from path
            parts = path.split('/')
            notification_id = None
            for i, part in enumerate(parts):
                if part == 'notifications' and i + 1 < len(parts):
                    notification_id = parts[i + 1]
                    break
            return mark_notification_read(notification_id, headers)
        # Route: GET /profiles
        elif http_method == 'GET' and '/profiles' in path:
            return get_profiles(headers)
        # Route: PUT /profiles
        elif http_method == 'PUT' and '/profiles' in path:
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


def get_notifications(headers):
    """Get all notifications (unread first)."""
    try:
        response = s3.get_object(Bucket=BUCKET_NAME, Key='data/notifications.json')
        data = json.loads(response['Body'].read().decode('utf-8'))
        notifications = data.get('notifications', [])
        # Sort: unread first, then by created_at descending
        notifications.sort(key=lambda x: (x.get('read', False), x.get('created_at', '')), reverse=False)
        notifications.sort(key=lambda x: x.get('created_at', ''), reverse=True)
        unread_first = [n for n in notifications if not n.get('read', False)] + [n for n in notifications if n.get('read', False)]
        return {
            'statusCode': 200,
            'headers': headers,
            'body': json.dumps({
                'notifications': unread_first[:50],
                'unread_count': len([n for n in notifications if not n.get('read', False)])
            })
        }
    except s3.exceptions.NoSuchKey:
        return {
            'statusCode': 200,
            'headers': headers,
            'body': json.dumps({'notifications': [], 'unread_count': 0})
        }


def mark_notification_read(notification_id, headers):
    """Mark a single notification as read."""
    if not notification_id:
        return {
            'statusCode': 400,
            'headers': headers,
            'body': json.dumps({'error': 'Notification ID required'})
        }

    try:
        response = s3.get_object(Bucket=BUCKET_NAME, Key='data/notifications.json')
        data = json.loads(response['Body'].read().decode('utf-8'))
        notifications = data.get('notifications', [])

        updated = False
        for n in notifications:
            if n.get('id') == notification_id:
                n['read'] = True
                updated = True
                break

        if updated:
            s3.put_object(
                Bucket=BUCKET_NAME,
                Key='data/notifications.json',
                Body=json.dumps(data, indent=2, ensure_ascii=False),
                ContentType='application/json'
            )

        return {
            'statusCode': 200,
            'headers': headers,
            'body': json.dumps({'success': True})
        }
    except Exception as e:
        return {
            'statusCode': 500,
            'headers': headers,
            'body': json.dumps({'error': str(e)})
        }


def mark_all_notifications_read(headers):
    """Mark all notifications as read."""
    try:
        response = s3.get_object(Bucket=BUCKET_NAME, Key='data/notifications.json')
        data = json.loads(response['Body'].read().decode('utf-8'))
        notifications = data.get('notifications', [])

        for n in notifications:
            n['read'] = True

        s3.put_object(
            Bucket=BUCKET_NAME,
            Key='data/notifications.json',
            Body=json.dumps(data, indent=2, ensure_ascii=False),
            ContentType='application/json'
        )

        return {
            'statusCode': 200,
            'headers': headers,
            'body': json.dumps({'success': True})
        }
    except s3.exceptions.NoSuchKey:
        return {
            'statusCode': 200,
            'headers': headers,
            'body': json.dumps({'success': True})
        }
    except Exception as e:
        return {
            'statusCode': 500,
            'headers': headers,
            'body': json.dumps({'error': str(e)})
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

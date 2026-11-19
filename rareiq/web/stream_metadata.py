"""Loopback producer commands for explicit platform metadata edits."""
from __future__ import annotations

import asyncio
import inspect
import json
import re
from urllib.parse import urlsplit

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from starlette.requests import ClientDisconnect

from rareiq.web.remote_access import is_loopback_client

MAX_BYTES = 32768
SAFE_REASONS = frozenset('''
authorization_required app_setup_required metadata_scope_required account_state_changed
account_identity_mismatch provider_unavailable provider_rate_limited provider_response_too_large
invalid_provider_response invalid_stream_info invalid_platform invalid_request_id
channel_mismatch broadcast_selection_required broadcast_not_found broadcast_not_owned
category_not_found invalid_category invalid_tags invalid_title unsupported_field
request_conflict update_unconfirmed verification_failed authorization_rejected
streaming_scope_required youtube_channel_required kick_channel_required
invalid_metadata invalid_description invalid_category_id invalid_channel_id unsupported_metadata_field
stream_info_scope_required request_id_conflict category_query_too_short metadata_requests_full
unsupported_platform invalid_broadcast_id receipt_capacity_reached provider_rejected
broadcast_unavailable invalid_provider_endpoint authorization_refresh_required account_storage_unavailable
metadata_precondition_required unsupported_broadcast_selection readback_unavailable readback_mismatch
metadata_recovery_storage_invalid metadata_recovery_storage_unavailable
'''.split())


async def _result(value):
    return await value if inspect.isawaitable(value) else value


def create_stream_metadata_router(service, authorize_operator, *, audit=None, can_apply=lambda: True):
    router = APIRouter()

    def response(value, status=200):
        return JSONResponse(value, status_code=status, headers={'Cache-Control': 'no-store'})

    @router.post('/api/production/stream-metadata/{platform}/{action}')
    async def command(platform: str, action: str, request: Request):
        try:
            parsed = urlsplit(str(request.url))
            expected = parsed.scheme + '://' + parsed.netloc
            if (not request.client or not is_loopback_client(request.client.host)
                    or not is_loopback_client(parsed.hostname) or parsed.username or parsed.password
                    or len(request.headers.getlist('host')) != 1
                    or await _result(authorize_operator(request)) is not True):
                return response({'ok': False, 'reason': 'local_operator_required'}, 403)
            if (request.headers.getlist('origin') != [expected]
                    or request.headers.get('sec-fetch-site') not in (None, 'same-origin', 'none')):
                return response({'ok': False, 'reason': 'same_origin_required'}, 403)
            if platform not in {'twitch', 'youtube', 'kick'} or action not in {'inspect', 'categories', 'apply'}:
                return response({'ok': False, 'reason': 'invalid_stream_info'}, 404)
            types, lengths = request.headers.getlist('content-type'), request.headers.getlist('content-length')
            if (len(types) != 1 or types[0].split(';', 1)[0].strip().lower() != 'application/json'
                    or lengths and (len(lengths) != 1 or not re.fullmatch(r'[0-9]{1,10}', lengths[0])
                                    or int(lengths[0]) > MAX_BYTES)):
                return response({'ok': False, 'reason': 'invalid_stream_info'}, 400)

            async def read():
                data = bytearray()
                async for chunk in request.stream():
                    if len(data) + len(chunk) > MAX_BYTES:
                        raise ValueError()
                    data.extend(chunk)
                return json.loads(bytes(data).decode('utf-8'))

            try:
                payload = await asyncio.wait_for(read(), 5)
            except (ValueError, TypeError, TimeoutError, ClientDisconnect):
                return response({'ok': False, 'reason': 'invalid_stream_info'}, 400)
            allowed = {'inspect': {'broadcast_id'}, 'categories': {'query'},
                       'apply': {'request_id', 'expected_channel_id', 'broadcast_id', 'values'}}[action]
            if not isinstance(payload, dict) or not set(payload) <= allowed:
                return response({'ok': False, 'reason': 'invalid_stream_info'}, 400)
            for key in ('broadcast_id', 'query', 'request_id', 'expected_channel_id'):
                if key in payload and (not isinstance(payload[key], str) or len(payload[key]) > 200
                                       or any(ord(c) < 32 or ord(c) == 127 for c in payload[key])):
                    return response({'ok': False, 'reason': 'invalid_stream_info'}, 400)
            if action == 'apply':
                if not {'request_id', 'expected_channel_id', 'values'} <= set(payload):
                    return response({'ok': False, 'reason': 'invalid_stream_info'}, 400)
                if await _result(can_apply()) is not True:
                    return response({'ok': False, 'reason': 'destination_broadcast_busy'}, 409)
                if audit is not None:
                    try:
                        await _result(audit(platform=platform, outcome='requested'))
                    except Exception:
                        return response({'ok': False, 'reason': 'activity_history_unavailable'}, 503)
            try:
                if action == 'inspect':
                    result = await service.inspect(platform, broadcast_id=payload.get('broadcast_id'))
                elif action == 'categories':
                    result = await service.categories(platform, payload.get('query', ''))
                else:
                    result = await service.apply(platform, payload['values'], payload['request_id'],
                                                 payload['expected_channel_id'], broadcast_id=payload.get('broadcast_id'))
            except ValueError as error:
                reason = str(error) if str(error) in SAFE_REASONS else 'provider_unavailable'
                if action == 'apply' and audit is not None:
                    try:
                        await _result(audit(platform=platform, outcome='failed'))
                    except Exception:
                        pass
                return response({'ok': False, 'reason': reason}, 409)
            warning = False
            if action == 'apply' and audit is not None:
                try:
                    await _result(audit(platform=platform, outcome='succeeded' if result.get('state') == 'applied' else 'failed'))
                except Exception:
                    warning = True
            return response({**result, 'ok': True, **({'activity_history_warning': True} if warning else {})})
        except Exception:
            return response({'ok': False, 'reason': 'provider_unavailable'}, 503)
    return router

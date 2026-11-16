"""Invitation-authenticated room view and reversible waiting-room moderation."""
import asyncio
import json
from contextlib import contextmanager
from contextlib import suppress

import pytest
from starlette.websockets import WebSocketDisconnect

from rareiq.services.greenroom_service import EMPTY_MEDIA, GreenroomError
from rareiq.web.greenroom import Peer
from test_greenroom_routes import fixture, join, socket, next_type, OPERATOR, ORIGIN, SDP
from test_greenroom_pump import Socket
from test_guest_ingress import exercise, scope


@contextmanager
def view(client, token):
    with client.websocket_connect('/guest/view/ws', headers=ORIGIN) as connection:
        connection.send_json({'type': 'authenticate', 'token': token})
        hello = connection.receive_json()
        assert hello['role'] == 'guest-view'
        yield connection, hello


def test_view_requires_invitation_and_does_not_create_publisher_presence(fixture):
    service, _, _, _, client = fixture
    _, person, token = join(fixture)
    with view(client, token) as (connection, _):
        state = next_type(connection, 'state')
        assert state['subscriptions'] == []
        assert set(state['room']) == {'room_id', 'active', 'participants'}
        assert not service.authenticate(token)['connected']
        assert all(set(p) <= {'id','name','state','connected','expired','media','sources'} for p in state['room']['participants'])
    with pytest.raises(WebSocketDisconnect):
        with view(client, '0' * 64):
            pass


def test_view_close_cannot_disconnect_publisher_and_publisher_loss_is_not_hidden(fixture):
    service, _, _, _, client = fixture
    _, person, token = join(fixture)
    with socket(client, 'guest', token):
        with view(client, token):
            assert service.authenticate(token)['connected']
        assert service.authenticate(token)['connected']
    with view(client, token):
        assert not service.authenticate(token)['connected']
        with socket(client, 'guest', token):
            assert service.authenticate(token)['connected']
        # The view-only socket must not keep source permissions alive.
        assert not service.authenticate(token)['connected']


def test_camera_subscriptions_require_both_admissions_and_exclude_self(fixture):
    service, hub, _, _, _ = fixture
    _, alice, ta = join(fixture, 1)
    _, bob, tb = join(fixture, 2)
    for p in [alice, bob]:
        service.set_connected(p['id'], True)
        service.update_media(p['id'], dict.fromkeys(EMPTY_MEDIA, True))
    viewer = Peer(Socket(), 'guest-view', participant_id=bob['id'], token=tb)
    assert hub._allowed_sources(viewer, hub._snapshot()) == ()
    service.moderate(alice['id'], 'admit')
    assert hub._allowed_sources(viewer, hub._snapshot()) == ()
    service.moderate(bob['id'], 'admit')
    assert hub._allowed_sources(viewer, hub._snapshot()) == (alice['sources']['camera'],)
    service.moderate(alice['id'], 'wait')
    assert hub._allowed_sources(viewer, hub._snapshot()) == ()
    service.moderate(alice['id'], 'admit')
    service.moderate(bob['id'], 'wait')
    assert hub._allowed_sources(viewer, hub._snapshot()) == ()
    service.moderate(bob['id'], 'remove')
    with pytest.raises(GreenroomError):
        hub._allowed_sources(viewer, hub._snapshot())


def test_wait_keeps_session_and_capture_then_readmits_without_new_invitation(fixture):
    service, _, _, removed, client = fixture
    _, person, token = join(fixture)
    service.set_connected(person['id'], True)
    service.update_media(person['id'], EMPTY_MEDIA | {'camera': True, 'microphone': True})
    service.moderate(person['id'], 'admit')
    body = {'action':'wait', 'expected_revision':service.snapshot()['revision'], 'request_id':'wait-once'}
    result = client.post('/api/production/greenroom/participants/'+person['id'], headers=OPERATOR, json=body)
    assert result.status_code == 200
    assert removed == [person['id']]
    waiting = service.authenticate(token)
    assert waiting['state'] == 'waiting' and waiting['connected'] and waiting['media']['camera']
    assert not service.source_available(person['sources']['camera'])
    service.moderate(person['id'], 'admit')
    assert service.source_available(person['sources']['camera'])
    # Late duplicate response is not a new wait action and cannot clear a new shot.
    result = client.post('/api/production/greenroom/participants/'+person['id'], headers=OPERATOR, json=body)
    assert result.status_code == 200 and removed == [person['id']]
    assert service.authenticate(token)['state'] == 'admitted'
    service.moderate(person['id'], 'remove')
    with pytest.raises(GreenroomError):
        service.authenticate(token)
    with pytest.raises(GreenroomError):
        service.moderate(person['id'], 'admit')


def test_wait_action_requires_producer_and_revision(fixture):
    service, _, _, _, client = fixture
    _, person, _ = join(fixture)
    url='/api/production/greenroom/participants/'+person['id']
    body={'action':'wait','expected_revision':service.snapshot()['revision'],'request_id':'wait'}
    assert client.post(url,headers=ORIGIN,json=body).status_code == 403
    assert client.post(url,headers=OPERATOR,json={**body,'expected_revision':0}).status_code == 409


def test_guest_view_has_camera_only_subscription_and_signal_access(fixture):
    service, hub, _, _, _ = fixture
    _, alice, ta = join(fixture, 1)
    _, bob, tb = join(fixture, 2)
    for p in [alice,bob]:
        service.moderate(p['id'],'admit');service.set_connected(p['id'],True)
        service.update_media(p['id'],dict.fromkeys(EMPTY_MEDIA, True))
    publisher=Peer(Socket(),'guest',participant_id=alice['id'],token=ta)
    receiver=Peer(Socket(),'guest-view',participant_id=bob['id'],token=tb)
    hub.peers={'a'*32:publisher,'b'*32:receiver}
    async def check():
        await hub._pump_peer('a'*32,publisher,hub._snapshot(),[])
        assert publisher.socket.messages[-1]['subscriptions'] == [{'peer_id':'b'*32,'role':'guest-view','sources':['camera'],'return_audio':False}]
        packet={'type':'signal','to':'b'*32,'kind':'offer','data':{'type':'offer','sdp':SDP}}
        await hub._message('a'*32,publisher,packet)
        assert receiver.socket.messages[-1]['type']=='signal'
        service.moderate(bob['id'],'wait')
        with pytest.raises(ValueError,match='subscription_not_allowed'):
            await hub._message('a'*32,publisher,packet)
        service.moderate(bob['id'],'remove')
        with pytest.raises(GreenroomError):
            await hub._message('a'*32,publisher,packet)
    asyncio.run(check())


@pytest.mark.parametrize('action',['remove','close'])
def test_ended_access_closes_view_socket(fixture,action):
    service, _, _, _, client=fixture
    _,person,token=join(fixture)
    with view(client,token) as (connection,_):
        body={'expected_revision':service.snapshot()['revision'],'request_id':'end-'+action}
        url='/api/production/greenroom/room/close'
        if action=='remove':
            body['action']='remove';url='/api/production/greenroom/participants/'+person['id']
        assert client.post(url,headers=OPERATOR,json=body).status_code==200
        with pytest.raises(WebSocketDisconnect):
            for _ in range(12): connection.receive_json()


def test_private_ingress_view_socket_preserves_boundary():
    calls,_=exercise(scope('/guest/view/ws',kind='websocket'),[{'type':'websocket.connect'}])
    assert len(calls)==1 and calls[0][0]['path']=='/guest/view/ws'
    calls,sent=exercise(scope('/guest/view/ws',kind='websocket',query_string=b'token=secret'))
    assert not calls and sent[0]['type']=='websocket.close'


@pytest.mark.parametrize('role',['guest','guest-view'])
def test_concurrent_reconnect_reserves_newest_peer_before_slow_close(fixture,role):
    service,hub,_,_,_=fixture
    _,person,token=join(fixture)
    async def check():
        old,first,second=Socket(stall_close=True),Socket(stall_close=True),Socket()
        hub.peers={'a'*32:Peer(old,role,participant_id=person['id'],token=token)}
        hub.CLOSE_TIMEOUT=.3
        packet={'type':'websocket.receive','text':json.dumps({'type':'authenticate','token':token})}
        await first.incoming.put(packet);await second.incoming.put(packet)
        tasks=[]
        try:
            tasks.append(asyncio.create_task(hub._serve(first,role)))
            await asyncio.wait_for(old.closing.wait(),1)
            assert any(p.socket is first for p in hub.peers.values())
            tasks.append(asyncio.create_task(hub._serve(second,role)))
            await asyncio.wait_for(first.closing.wait(),1)
            old.release.set();first.release.set()
            await asyncio.wait_for(second.sent.wait(),1)
            await asyncio.wait_for(tasks[0],1)
            peers=[p for p in hub.peers.values() if p.role==role]
            assert len(peers)==1 and peers[0].socket is second
            assert not any(m.get('type')=='hello' for m in first.messages)
            if role=='guest': assert service.authenticate(token)['connected']
        finally:
            for task in tasks:
                if not task.done(): task.cancel()
                with suppress(asyncio.CancelledError): await task
            if hub._pump_task:
                hub._pump_task.cancel()
                with suppress(asyncio.CancelledError): await hub._pump_task
    asyncio.run(check())

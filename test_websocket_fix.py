import asyncio
import json
import websockets
import time
import requests

async def test_websocket():
    try:
        # Step 1: Create a session and get the token
        session_resp = requests.post('http://localhost:8000/session').json()
        session_id = session_resp['session_id']
        token = session_resp['token']
        print(f'✓ Session created: {session_id[:8]}...')
        
        # Step 2: Connect WebSocket with the session_id
        uri = f'ws://localhost:8000/ws/{session_id}'
        async with websockets.connect(uri) as ws:
            print('✓ WebSocket connected')
            
            # Step 3: Start session with the token
            await ws.send(json.dumps({
                'type': 'start_session',
                'token': token,
                'domain': 'informatique',
                'language': 'fr'
            }))
            resp = await asyncio.wait_for(ws.recv(), timeout=5)
            print(f'✓ Session started')
            
            # Step 4: Get course structure to find valid course ID
            try:
                resp_data = requests.get('http://localhost:8000/course/list').json()
                courses = resp_data.get('courses', [])
                if not courses:
                    print('✗ No courses found')
                    return
                
                course_id = courses[0]['id']
                print(f'✓ Using course: {course_id}')
            except Exception as e:
                print(f'✗ Error getting courses: {e}')
                return
            
            # Step 5: Start presentation - MEASURE TIME
            start_time = time.time()
            await ws.send(json.dumps({'type': 'start_presentation', 'course_id': course_id}))
            
            # Step 6: Wait for presentation_started event
            resp = await asyncio.wait_for(ws.recv(), timeout=10)
            elapsed = time.time() - start_time
            data = json.loads(resp)
            
            print(f'✓ Event received in {elapsed:.2f}s')
            print(f'  Event type: {data.get("type")}')
            
            if data.get('type') == 'presentation_started':
                print(f'  course: {data.get("course")}')
                print(f'  chapter: {data.get("chapter")}')
                print(f'  section: {data.get("section")}')
                print(f'  image_url: {data.get("image_url")}')
                if elapsed < 3:
                    print(f'\n✓ SUCCESS: presentation_started emitted immediately ({elapsed:.2f}s)')
                    print('  The fix is working - frontend will render the slide without waiting')
                else:
                    print(f'\n⚠ SLOW: presentation_started took {elapsed:.2f}s (expected <3s)')
            else:
                print(f'✗ Unexpected event type: {data.get("type")}')
    except Exception as e:
        import traceback
        print(f'✗ Error: {e}')
        traceback.print_exc()

asyncio.run(test_websocket())

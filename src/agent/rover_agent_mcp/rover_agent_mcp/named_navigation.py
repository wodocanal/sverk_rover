"""MCP tools for destinations owned by the web navigation manager."""
import json
import math
import time

from rover_interfaces.srv import NamedPlaces

from .utils import parse_bool


class NamedNavigationMixin:
    def init_named_navigation(self):
        self.declare_parameter('named_places_service', '/rover/named_places')
        self._named_places_client = self.create_client(
            NamedPlaces, str(self.get_parameter('named_places_service').value))
        self._named_navigation_token = None

    def _named_places_call(self, command, request=None):
        if not self._named_places_client.wait_for_service(timeout_sec=2.0):
            return {'success': False, 'error': 'Named places service unavailable. Start rover-web and check ROS_DOMAIN_ID.'}
        message = NamedPlaces.Request()
        message.command = command
        message.request_json = json.dumps(request or {}, ensure_ascii=False, allow_nan=False)
        future = self._named_places_client.call_async(message)
        if not self._wait_future(future, 8.0):
            return {'success': False, 'error': 'Named places service timed out; outcome unknown. Check the web navigation status before retrying.'}
        response = future.result()
        if not response.success:
            return {'success': False, 'error': response.message}
        return {**json.loads(response.data_json), 'success': True}

    def list_named_places(self, map: str = ''):
        return self._named_places_call('list', {'map': map})

    def list_search_areas(self, map: str = ''):
        result = self._named_places_call('list', {'map': map})
        if not result.get('success'):
            return result
        areas = []
        for entry in result.get('maps', []):
            for zone in entry.get('zones', []):
                if not zone.get('can_drive'):
                    areas.append({
                        'name': zone['name'], 'aliases': list(zone.get('aliases', [])),
                        'map': entry['map'],
                    })
        return {'success': True, 'active_map': result.get('active_map'), 'areas': areas}

    def search_static_obstacle(
        self,
        static_obstacle: str,
        target_obstacle: str = 'any',
        wait_at_qr_sec: float = 5.0,
        return_point: str = 'старт',
        timeout_s: float = 600.0,
    ):
        timeout = float(timeout_s)
        dwell = float(wait_at_qr_sec)
        if not math.isfinite(timeout) or not 30.0 <= timeout <= 900.0:
            return {'success': False, 'error': 'timeout_s must be between 30 and 900 seconds'}
        if not math.isfinite(dwell) or not 0.0 <= dwell <= 30.0:
            return {'success': False, 'error': 'wait_at_qr_sec must be between 0 and 30 seconds'}
        started = self._named_places_call('start_inspection', {
            'name': static_obstacle,
            'target_obstacle': target_obstacle or 'any',
            'return_wait_sec': dwell,
        })
        if not started.get('success'):
            return started
        inspection = started['inspection']
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            status = self._named_places_call('inspection_status')
            if not status.get('success'):
                return status
            inspection = status['inspection']
            state = inspection.get('state')
            if state == 'returned':
                codes = list(inspection.get('qr_codes') or [])
                if inspection.get('completion_state') != 'succeeded' or not codes:
                    return {'success': False, 'inspection': inspection,
                            'error': inspection.get('completion_message', 'Inspection ended without decoded QR text')}
                return {
                    'success': True,
                    'inspection': inspection,
                    'qr_codes': codes,
                    'waited_at_qr_sec': dwell,
                    'return_to_start': {'success': True, 'completed': True, 'name': return_point},
                }
            if state == 'return_failed':
                return {
                    'success': False, 'inspection': inspection,
                    'error': inspection.get('message', 'Inspection completed, but the rover could not return to start'),
                }
            if state == 'canceled':
                return {
                    'success': False, 'inspection': inspection,
                    'error': inspection.get('message', f'Inspection ended as {state}'),
                }
            time.sleep(0.5)
        return {
            'success': False, 'inspection': inspection,
            'error': 'Timed out waiting for the zone inspection; inspect rover-web before retrying.',
        }

    def navigate_to_named_place(self, name: str, map: str = '',
                                wait_until_done: bool = True, timeout_s: float = 90.0):
        timeout = float(timeout_s)
        if not math.isfinite(timeout) or not 1 <= timeout <= 90:
            return {'success': False, 'error': 'timeout_s must be between 1 and 90 seconds'}
        if self._nav_status.get('active'):
            return {'success': False, 'error': 'Cancel the existing coordinate navigation goal first.'}
        result = self._named_places_call('navigate', {'name': name, 'map': map})
        if not result.get('success'):
            return result
        token = result['token']
        self._named_navigation_token = token
        if not parse_bool(wait_until_done, True):
            return {**result, 'completed': False, 'message': 'Goal queued, not reached yet. Poll get_navigation_status.'}
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            status = self._named_places_call('status', {'token': token})
            if not status.get('success'):
                cancel = self._named_places_call('cancel', {'token': token})
                return {**status, 'completed': False, 'cancel_result': cancel}
            runtime = status['navigation']
            state = runtime['goal_state']
            if state in {'succeeded', 'canceled', 'aborted', 'error', 'rejected', 'finished'} or not runtime['running']:
                return {**result, 'success': state == 'succeeded', 'completed': state == 'succeeded',
                        'navigation': runtime, 'message': runtime.get('goal_message', state)}
            time.sleep(0.25)
        cancel = self._named_places_call('cancel', {'token': token})
        return {**result, 'success': False, 'completed': False,
                'error': 'Timed out waiting for the destination; cancellation requested.', 'cancel_result': cancel}

    def named_navigation_status(self):
        result = self._named_places_call('status', {'token': self._named_navigation_token})
        if result.get('success'):
            state = result['navigation']['goal_state']
            result.update(active=state in {'queued', 'sending', 'active', 'canceling'},
                          status=state, completed=state == 'succeeded')
        return result

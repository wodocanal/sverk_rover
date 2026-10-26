"""Classical OpenCV marker detection on the original, unannotated frame."""
import cv2
import numpy as np

try:
    import zxingcpp
except ImportError:  # Keep the camera node usable until the optional decoder is installed.
    zxingcpp = None

ARUCO_DICTIONARIES = tuple(f'DICT_{bits}X{bits}_{count}' for bits in (4, 5, 6, 7)
                           for count in (50, 100, 250, 1000)) + ('DICT_ARUCO_ORIGINAL',)


class MarkerDetector:
    def __init__(self, *, aruco=False, qr=False, dictionary='DICT_4X4_50'):
        self.dictionary_name = dictionary
        self.dictionary = self.aruco_detector = self.qr_detector = None
        if dictionary not in ARUCO_DICTIONARIES:
            raise ValueError('Unsupported ArUco dictionary')
        if aruco:
            if not hasattr(cv2, 'aruco'):
                raise RuntimeError('OpenCV ArUco is unavailable; install an OpenCV build with aruco support')
            self.dictionary = cv2.aruco.getPredefinedDictionary(getattr(cv2.aruco, dictionary))
            if hasattr(cv2.aruco, 'ArucoDetector'):
                self.aruco_detector = cv2.aruco.ArucoDetector(self.dictionary)
        if qr:
            self.qr_detector = cv2.QRCodeDetector()

    @staticmethod
    def _result(kind, corners, *, marker_id=None, data=None, dictionary=None):
        points = np.asarray(corners, dtype=float).reshape(4, 2)
        low, high = points.min(axis=0), points.max(axis=0)
        result = dict(kind=kind, label=f'ArUco {marker_id}' if kind == 'aruco' else 'QR',
                      corners=points.tolist(),
                      bbox=dict(x=int(low[0]), y=int(low[1]),
                                width=int(high[0]-low[0]), height=int(high[1]-low[1])))
        if kind == 'aruco':
            result.update(marker_id=int(marker_id), dictionary=dictionary)
        else:
            result.update(data=data or '', decoded=bool(data))
        return result

    def detect(self, frame):
        results = []
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        if self.dictionary is not None:
            if self.aruco_detector is not None:
                corners, ids, _ = self.aruco_detector.detectMarkers(gray)
            else:
                corners, ids, _ = cv2.aruco.detectMarkers(gray, self.dictionary)
            if ids is not None:
                results.extend(self._result('aruco', points, marker_id=marker_id,
                    dictionary=self.dictionary_name) for points, marker_id in zip(corners, ids.flatten()))
        if self.qr_detector is not None:
            decoded = zxingcpp.read_barcodes(
                gray,
                formats=zxingcpp.BarcodeFormat.QRCode,
                try_rotate=True,
                try_downscale=True,
            ) if zxingcpp is not None else []
            if decoded:
                for code in decoded:
                    position = code.position
                    corners = [
                        [position.top_left.x, position.top_left.y],
                        [position.top_right.x, position.top_right.y],
                        [position.bottom_right.x, position.bottom_right.y],
                        [position.bottom_left.x, position.bottom_left.y],
                    ]
                    results.append(self._result('qr', corners, data=code.text))
                return results
            try:
                _, texts, points, _ = self.qr_detector.detectAndDecodeMulti(gray)
            except UnicodeError:
                _, points = self.qr_detector.detectMulti(gray)
                texts = ()
            texts = texts or ()
            if points is not None and len(points):
                for index, corners in enumerate(points):
                    data = texts[index] if index < len(texts) else ''
                    results.append(self._result('qr', corners, data=data))
            else:
                try:
                    data, points, _ = self.qr_detector.detectAndDecode(gray)
                except UnicodeError:
                    _, points = self.qr_detector.detect(gray)
                    data = ''
                if points is not None:
                    results.append(self._result('qr', points, data=data))
        return results

    @staticmethod
    def annotate(frame, markers, thickness=2):
        for marker in markers:
            points = np.rint(marker['corners']).astype(np.int32)
            color = (255, 170, 0) if marker['kind'] == 'aruco' else (0, 180, 80)
            cv2.polylines(frame, [points], True, color, thickness, cv2.LINE_AA)
            x, y = points[0]
            # Payloads (URLs/text) are data only; never execute or open them.
            cv2.putText(frame, marker['label'], (max(0, int(x)), max(16, int(y)-6)),
                        cv2.FONT_HERSHEY_SIMPLEX, .55, color, thickness, cv2.LINE_AA)
        return frame

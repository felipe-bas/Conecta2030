# V2X Message JSON Patterns

Based on J2735 and Commsignia SDK documentation.

## 1. Basic Safety Message (BSM)
Used for vehicle state (heartbeat).
```json
{
  "bsm": {
    "messageId": 20,
    "value": {
      "coreData": {
        "msgCnt": 1,
        "id": "01020304",
        "secMark": 12000,
        "lat": -235497100,
        "long": -466327292,
        "elev": 100,
        "accuracy": { "semiMajor": 40, "semiMinor": 40, "orientation": 0 },
        "transmission": "forwardGears",
        "speed": 200,
        "heading": 28800,
        "angle": 0,
        "accelSet": { "long": 0, "lat": 0, "vert": 0, "yaw": 0 },
        "brakes": {
          "wheelBrakes": "10000",
          "traction": "unavailable",
          "abs": "engaged",
          "scs": "unavailable",
          "brakeBoost": "off",
          "auxBrakes": "unavailable"
        },
        "size": { "width": 200, "length": 500 }
      },
      "partII": [
        {
          "partII-Id": 0,
          "partII-Value": {
            "vehicleSafetyExtensions": {
              "events": "0000000000000",
              "pathHistory": {
                "crumbData": []
              },
              "pathPrediction": { "radiusOfCurve": 32767, "confidence": 200 }
            }
          }
        }
      ]
    }
  }
}
```

## 2. Map Data (MAP)
Static topology.
```json
{
  "mapData": {
    "msgIssueRevision": 1,
    "layerType": "intersectionData",
    "layerID": 0,
    "intersections": [
      {
        "id": { "region": 0, "id": 1 },
        "revision": 1,
        "refPoint": { "lat": -235500000, "long": -466330000, "elevation": 0 },
        "laneWidth": 300,
        "speedLimits": [ { "type": "vehicleMaxSpeed", "speed": 500 } ],
        "laneSet": [
          {
            "laneID": 1,
            "ingressApproach": 1,
            "laneAttributes": {
              "directionalUse": "10",
              "sharedWith": "0000000000",
              "laneType": { "vehicle": "000000000010" }
            },
            "maneuvers": "000000000010",
            "nodeList": {
              "nodes": [
                { "delta": { "node-XY1": { "x": 0, "y": 0 } } },
                { "delta": { "node-XY1": { "x": 100, "y": 0 } } }
              ]
            },
            "connectsTo": [
              {
                "connectingLane": { "lane": 2, "maneuver": "000000000010" },
                "signalGroup": 1
              }
            ]
          }
        ]
      }
    ]
  }
}
```

## 3. Signal Phase and Timing (SPAT)
Dynamic signal state.
```json
{
  "spat": {
    "msgCnt": 1,
    "intersections": [
      {
        "id": { "region": 0, "id": 1 },
        "revision": 1,
        "status": "0000000000000000",
        "states": [
          {
            "signalGroup": 1,
            "state-time-speed": [
              {
                "eventState": "protected-Movement-Allowed",
                "timing": {
                  "minEndTime": 100,
                  "maxEndTime": 200
                }
              }
            ]
          }
        ]
      }
    ]
  }
}
```

## 4. Roadside Alert (RSA)
Warnings.
```json
{
  "rsa": {
    "msgCnt": 1,
    "typeEvent": 1231,
    "description": [ 100, 200 ],
    "priority": "00",
    "heading": 0,
    "extent": "useInstantly",
    "position": { "lat": -235500000, "long": -466330000, "elevation": 0 },
    "furtherInfoID": "0000",
    "regional": []
  }
}
```

## 5. Traveler Information Message (TIM)
Advisory info.
```json
{
  "tim": {
    "msgCnt": 1,
    "timeStamp": 1000,
    "packetID": "010203040506070809",
    "urlB": "null",
    "dataFrames": [
      {
        "sspTimRights": 0,
        "frameType": "advisory",
        "msgId": {
          "roadSignID": {
            "position": { "lat": -235500000, "long": -466330000, "elevation": 0 },
            "viewAngle": "0000000000000000",
            "mutcdCode": "warning", 
            "crc": "0000"
          }
        },
        "priority": 0,
        "duratonTime": 100,
        "regions": [],
        "content": {
          "advisory": {
             "itemList": [
                {
                   "itis": 123
                }
             ]
          }
        },
        "url": "null"
      }
    ]
  }
}
```

## 6. Personal Safety Message (PSM)
VRU / Pedestrian.
```json
{
  "psm": {
    "basicType": "aPEDESTRIAN",
    "msgCnt": 1,
    "id": "00000044",
    "secMark": 1000,
    "position": { "lat": -235497100, "long": -466327292, "elevation": 0 },
    "accuracy": { "semiMajor": 40, "semiMinor": 40, "orientation": 8192 },
    "speed": 100,
    "heading": 0,
    "pathHistory": {
      "crumbData": []
    },
    "pathPrediction": { "radiusOfCurve": 32767, "confidence": 200 },
    "propulsion": { "human": "onFoot" },
    "useState": { "glance": "unavailable", "active": true }
  }
}
```

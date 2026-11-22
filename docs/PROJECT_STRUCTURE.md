# Fleet Guardian Project Structure

```text
Risk_Aware_Driver_Safety_Monitoring_System/
│
├── config/
│   └── config.json
│
├── data/
│   ├── config.json
│   ├── fleet.sqlite3
│   ├── fleet.log
│   └── gps-cert/
│       ├── phone-ca.crt
│       ├── server.crt
│       └── server.key
│
├── docs/
│   ├── CODE_GUIDE.md
│   ├── MODEL_INTEGRATION.md
│   └── PROJECT_STRUCTURE.md
│
├── fleet/
│   ├── manager/
│   │   ├── owner/
│   │   │   ├── __init__.py
│   │   │   ├── background.py
│   │   │   ├── dashboard_page.py
│   │   │   ├── fleet_page.py
│   │   │   ├── owner_ui.py
│   │   │   ├── phone_page.py
│   │   │   └── reports_page.py
│   │   ├── __init__.py
│   │   ├── mobile_assets.py
│   │   ├── mobile_config.py
│   │   ├── mobile_handler.py
│   │   ├── mobile_processing.py
│   │   ├── network.py
│   │   ├── phone_manager.py
│   │   ├── server.py
│   │   ├── storage.py
│   │   ├── ui_common.py
│   │   └── vehicle_link.py
│   │
│   ├── mobile/
│   │   ├── css/
│   │   │   └── mobile.css
│   │   ├── js/
│   │   │   ├── camera.js
│   │   │   ├── config.js
│   │   │   ├── inference.js
│   │   │   ├── main.js
│   │   │   ├── sensors.js
│   │   │   └── ui.js
│   │   ├── mobile.html
│   │   └── phone_speed.py
│   │
│   ├── perception/
│   │   └── trained_model.py
│   │
│   ├── risk/
│   │   ├── attention.py
│   │   └── engine.py
│   │
│   └── tunnel/
│       └── cloudflare.py
│
├── models/
│   └── driver_mobilenetv3_small.onnx
│
├── tools/
│   ├── cloudflared.exe
│   ├── create_gps_certificate.py
│   └── show_structure.py
│
├── .gitignore
├── main.py
├── README.md
├── requirements.txt
└── run.bat
```

## Main directories

- `config/`: Static application configuration.
- `data/`: Runtime configuration, database, logs and certificates.
- `docs/`: Project documentation.
- `fleet/manager/`: Fleet server, storage, networking and owner GUI.
- `fleet/mobile/`: Smartphone interface, camera and sensors.
- `fleet/perception/`: Driver behaviour prediction.
- `fleet/risk/`: Risk assessment and attention rules.
- `fleet/tunnel/`: Cloudflare tunnel management.
- `models/`: ONNX model files.
- `tools/`: Setup and development utilities.

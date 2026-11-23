# Fleet Guardian – Risk-Aware Driver Safety Monitoring System

Fleet Guardian is an AI-powered driver safety monitoring system that detects unsafe driving behaviours and monitors driver risk through a centralized fleet management dashboard.

The system uses a smartphone camera for driver behaviour detection, GPS for speed monitoring, and a Python-based risk engine to assess driving risk.

## Features

- AI-based driver behaviour detection using a nine-class ONNX model.
- Real-time drowsiness and attention monitoring.
- GPS-based speed monitoring.
- Explainable risk score and risk levels.
- Centralized fleet management dashboard.
- Individual driver and vehicle monitoring sessions.
- Monitoring history and event logs.
- SQLite database for storing fleet information.

## Technologies Used

- Python
- Tkinter
- SQLite
- OpenCV
- MediaPipe
- ONNX Runtime Web
- MobileNetV3 Small
- HTML, CSS and JavaScript
- Cloudflare Quick Tunnel

## Requirements

- Windows PC
- Python and pip installed
- Google Chrome on the driver's smartphone
- Smartphone with a working camera and GPS
- Internet connection for remote monitoring

## Installation and Running

### 1. Clone the repository

```bash
git clone https://github.com/DevKumbharvadia/Risk_Aware_Driver_Safety_Monitoring_System.git
```

### 2. Open the project folder

```bash
cd Risk_Aware_Driver_Safety_Monitoring_System
```

### 3. Start the application

**Recommended method (Windows):**

```bash
run.bat
```

The startup script automatically creates a virtual environment, installs the required dependencies on the first run, and launches the application.

**Alternative method:**

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

## Connecting a Driver's Smartphone

1. Launch the Fleet Guardian application.
2. Open the **Connect a Driver Phone** window.
3. Select the vehicle.
4. Copy its generated monitoring link.
5. Open the link in Google Chrome on the driver's smartphone.
6. Allow camera and location permissions.
7. Start monitoring.

### Remote Monitoring

To connect smartphones using mobile data, run:

```bash
python main.py --trip
```

The application starts a Cloudflare Quick Tunnel and generates a public HTTPS monitoring link.

Share the vehicle-specific link with the driver to start monitoring remotely.

## Risk Monitoring

The system evaluates driver behaviour, behaviour duration and GPS speed to calculate a risk score.

Risk levels:

- LOW: 0–29
- CAUTION: 30–69
- HIGH: 70–100
- UNKNOWN: Monitoring data unavailable

## Disclaimer

This project is developed for educational and research purposes. It is an experimental driver monitoring system and is not a certified automotive safety solution.
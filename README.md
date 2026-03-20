# Academic Access Control and Authentication System (AACAS)

This project is an Academic Access Control and Authentication System (AACAS) that uses biometric verification to control access to exam halls. It is designed to be a distributed system with edge computing nodes, a central API, and a persistent data layer.

## System Architecture Overview

The system has a distributed microservices architecture to handle real-time biometric verification across multiple campus locations.

### Edge Computing Layer

-   ESP32-S3 nodes are deployed at exam hall entrances.
-   These nodes capture high-resolution frames when a PIR sensor is activated and send them to the core API.

### Central API Layer

-   A FastAPI-based central API handles asynchronous requests from multiple stations.
-   It orchestrates an AI pipeline for Face Detection, Liveness Verification (Anti-Spoofing), and Recognition.

### Persistent Data Layer

-   A PostgreSQL database is the single source of truth for student records and schedules.
-   The `pgvector` extension is used for high-speed biometric similarity searches.

**IMPORTANT:** To ensure privacy and GDPR compliance, the system does not use raw images for matching. Instead, it operates on 128-dimensional mathematical embeddings.

## Technology Stack

### Backend Framework

-   Python 3.11 with FastAPI (Asynchronous processing).

### AI/ML Modules

-   `face_recognition` (dlib-based) for biometric encoding.
-   PyTorch for MiniFASNet (Liveness Detection) to prevent spoofing.

### Database Engine

-   PostgreSQL 15+ with pgvector.

### Communication Protocols

-   RESTful API for image transmission.
-   WebSockets for real-time proctor notifications.

## Acknowledgements

This project uses the **Minivisions Silent Face Anti Spoofing** model for liveness detection. This model is licensed under the Apache 2.0 License.

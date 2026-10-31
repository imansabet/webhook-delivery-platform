# Reliable Webhook Delivery Platform

A multi-tenant webhook delivery service designed to reliably deliver events between independent systems.

## The Problem

Modern applications need to communicate with external services in real time. However, direct HTTP requests are unreliable due to network failures, endpoint downtime, timeouts, and temporary server errors.

## The Solution

This platform acts as a reliable middleware between event producers and consumers. It receives events, persists them, processes deliveries asynchronously, automatically retries failed requests, and tracks delivery status.

## Core Features

- Multi-tenant architecture
- Persistent event storage
- Asynchronous event processing
- Automatic retries with exponential backoff
- Dead Letter Queue (DLQ)
- HMAC request signing
- Delivery tracking and logs
- Idempotency support

## Main Goal

**Never silently lose an event. Make webhook delivery reliable, observable, and manageable.**
<img width="3902" height="612" alt="mermaid-diagram" src="https://github.com/user-attachments/assets/775075f2-6a0f-49c8-af4b-581a9225ff7f" />


import axios from 'axios';

// Use environment variable for API URL or default to localhost:8080 (API Gateway)
// In Docker, client-side requests go to localhost:8080 (mapped port)
// Server-side requests might need internal networking (handled by next.config.js rewrites or env vars)
const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8080';

export const api = axios.create({
    baseURL: API_URL,
    headers: {
        'Content-Type': 'application/json',
    },
});

export interface HealthStatus {
    service: string;
    status: 'online' | 'offline' | 'degraded';
    details?: string;
    timestamp: string;
}

export const fetchSystemHealth = async (): Promise<HealthStatus[]> => {
    // In a real app, you'd fetch this from the API Gateway's health endpoint
    // For now, we'll simulate it or hit the root endpoint
    try {
        // Check API Gateway
        await api.get('/');
        // If successful, Gateway is online. 
        // We can assume other services are traceable from there or mock them for now.

        return [
            { service: 'API Gateway', status: 'online', timestamp: new Date().toISOString() },
            { service: 'Ingestion Service', status: 'online', timestamp: new Date().toISOString() }, // Mock
            { service: 'Strategy Engine', status: 'online', timestamp: new Date().toISOString() },   // Mock
            { service: 'Feature Engine', status: 'online', timestamp: new Date().toISOString() },    // Mock
            { service: 'QuestDB', status: 'online', timestamp: new Date().toISOString() },           // Mock
        ];
    } catch (error) {
        console.error("Health check failed", error);
        return [
            { service: 'API Gateway', status: 'offline', timestamp: new Date().toISOString() },
            // Assume others offline if gateway is down
        ];
    }
};

-- ShorokAPI Database Schema (PostgreSQL + PostGIS)
-- ===============================================

-- Enable PostGIS extension
CREATE EXTENSION IF NOT EXISTS postgis;

-- 1. Identity & Access Management
-- Used by auth.py to manage API keys and usage tracking
CREATE TABLE IF NOT EXISTS api_keys (
    key_hash TEXT PRIMARY KEY,
    email TEXT NOT NULL,
    app_name TEXT NOT NULL,
    tier TEXT DEFAULT 'free', -- free, standard, pro
    daily_limit INTEGER DEFAULT 1000,
    active BOOLEAN DEFAULT true,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS api_logs (
    id BIGSERIAL PRIMARY KEY,
    key_hash TEXT REFERENCES api_keys(key_hash),
    endpoint TEXT NOT NULL,
    method TEXT NOT NULL,
    status_code INTEGER NOT NULL,
    log_date DATE DEFAULT CURRENT_DATE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 2. Spatial Intelligence Data
-- Used by source/spatial.py

-- Road network (OSM Data)
CREATE TABLE IF NOT EXISTS roads (
    osm_id BIGINT PRIMARY KEY,
    fclass TEXT,
    name TEXT,
    wkt_geometry GEOMETRY(LineString, 4326)
);
CREATE INDEX IF NOT EXISTS roads_geom_idx ON roads USING GIST (wkt_geometry);

-- Railway network
CREATE TABLE IF NOT EXISTS railways (
    osm_id BIGINT PRIMARY KEY,
    fclass TEXT,
    name TEXT,
    wkt_geometry GEOMETRY(LineString, 4326)
);

-- Transit points
CREATE TABLE IF NOT EXISTS transport_points (
    osm_id BIGINT PRIMARY KEY,
    fclass TEXT,
    name TEXT,
    geometry GEOMETRY(Point, 4326)
);

-- Live Traffic Data
CREATE TABLE IF NOT EXISTS traffic_live (
    id SERIAL PRIMARY KEY,
    osm_id BIGINT,
    congestion_level INTEGER,
    geometry GEOMETRY(LineString, 4326),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Incident Reports
CREATE TABLE IF NOT EXISTS incidents (
    id SERIAL PRIMARY KEY,
    lat FLOAT8,
    lon FLOAT8,
    category TEXT,
    details TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    geom GEOMETRY(Point, 4326) GENERATED ALWAYS AS (ST_SetSRID(ST_MakePoint(lon, lat), 4326)) STORED
);

-- Note: RPC functions (get_nearby_roads, reverse_geocode, etc.) 
-- should be defined in the database to support the API endpoints.
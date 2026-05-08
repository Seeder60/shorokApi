

## About

ShorokApi is a developer focused REST API built for Bangladesh.

It provides real time traffic conditions, ride fare estimation, routing,
and public transport data through a single interface.

## Features

Ride fare estimation for local transport\
Live traffic updates\
Routing based on OpenStreetMap data\
Public transport data\
API key authentication\
Usage analytics

## Supported Cities

Dhaka\
Chittagong\
Sylhet\
Rajshahi\
Khulna

## Quick Start

``` bash
curl "https://api.shorokapi.dev/v1/roads?fclass=primary&limit=5" \
  -H "X-API-Key: your_api_key_here"
```

### Response

``` json
{
  "status": "success",
  "fare": {
    "min": 120,
    "max": 160,
    "currency": "BDT",
    "vehicle_type": "cng",
    "distance_km": 5.4,
    "estimated_duration_min": 18
  }
}
```

## API Endpoints

### Fare

  Method   Endpoint         Description
  -------- ---------------- ---------------
  GET      /v1/fare         Estimate fare
  GET      /v1/fare/zones   Fare zones
  GET      /v1/fare/types   Vehicle types

### Traffic

  Method   Endpoint                Description
  -------- ----------------------- --------------------
  GET      /v1/traffic             Traffic conditions
  GET      /v1/traffic/incidents   Road incidents
  POST     /v1/traffic/report      Submit report

### Routing

  Method   Endpoint           Description
  -------- ------------------ -----------------
  GET      /v1/route          Directions
  GET      /v1/route/matrix   Distance matrix

### Transit

  Method   Endpoint               Description
  -------- ---------------------- --------------
  GET      /v1/transit/routes     Bus routes
  GET      /v1/transit/stops      Nearby stops
  GET      /v1/transit/schedule   Timetables

## Authentication

X-API-Key: your_api_key_here

## System Segments and Tags

The system contains multiple segments. Each segment has its own set of
tags. This structure is the source of truth.

  -----------------------------------------------------------------------
  Segment                                  Tags
  ---------------------------------------- ------------------------------
  roads                                    osm_id, code, fclass, name,
                                           ref, oneway, maxspeed, layer,
                                           bridge, tunnel, wkt_geometry,
                                           geom

  traffic                                  osm_id, code, fclass, name,
                                           ref, oneway, bridge, tunnel,
                                           calming, geometry, geom

  transport                                osm_id, code, fclass, name,
                                           geometry, geom

  transport_areas                          osm_id, code, fclass, name,
                                           geometry, geom

  railways                                 osm_id, code, fclass, name,
                                           ref, oneway, layer, bridge,
                                           tunnel, geometry, geom

  transit_stops                            stop_id, stop_name, stop_lat,
                                           stop_lon, geom

  transit_trips                            trip_id, route_id, service_id,
                                           trip_headsign
  -----------------------------------------------------------------------

## Notes

geom represents the PostGIS geometry column\
wkt_geometry or geometry represents raw WKT input before conversion\
roads and railways use LINESTRING geometry\
traffic and transport use POINT geometry\
transport_areas use POLYGON geometry\
transit_stops geometry is derived from latitude and longitude\
transit_trips does not contain geometry

Use this structure for schema design, API generation, and data
processing.

## Tech Stack

* **Backend**: FastAPI (Python 3.9+)
* **Database**: PostgreSQL with PostGIS extension
* **Routing Engine**: OSRM (Open Source Routing Machine)
* **Data Source**: OpenStreetMap (OSM) Bangladesh exports
* **Deployment**: Render / Docker
* **Security**: API Key + HMAC hashing

## Contributing

1. Fork the repository
2. Create a feature branch
3. Commit changes
4. Push changes
5. Open a pull request

## Self Hosting

``` bash
# Clone the repository
git clone https://github.com/shorokapi/backend.git
cd backend

# Setup environment
cp .env.example .env
# Required variables: SUPABASE_URL, SUPABASE_KEY, APIBASE_MASTERKEY, OSRM_URL

# Install dependencies
pip install -r requirements.txt

# Start production server
uvicorn main:app --host 0.0.0.0 --port 8000
```

## License

This project is licensed under the GNU General Public License.

You are free to use, modify, and distribute this software under the
terms of the GNU GPL. Any derivative work must also be distributed under
the same license.

This software is provided without warranty of any kind.

See the LICENSE file for full legal terms.

## Contact

Website https://shorokapi.dev\
Email hello@shorokapi.dev\
Issues https://github.com/yourusername/shorokapi/issues

::: {align="center" style="padding: 20px; opacity: 0.7;"}
Built for Bangladesh
:::

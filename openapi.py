"""OpenAPI 3.0 description of the JSON REST API, served at /api/openapi.json."""

SPEC = {
    "openapi": "3.0.3",
    "info": {
        "title": "RailYatra Booking API",
        "version": "1.1.0",
        "description": (
            "Train seat booking and allotment. Read endpoints are open; "
            "write endpoints require the X-API-Token header."
        ),
    },
    "servers": [{"url": "/"}],
    "components": {
        "securitySchemes": {
            "ApiToken": {"type": "apiKey", "in": "header", "name": "X-API-Token"}
        },
        "schemas": {
            "Passenger": {
                "type": "object",
                "required": ["name", "age"],
                "properties": {
                    "name": {"type": "string"},
                    "age": {"type": "integer", "minimum": 1, "maximum": 120},
                    "gender": {"type": "string", "enum": ["M", "F", "O"]},
                    "preference": {
                        "type": "string",
                        "enum": ["ANY", "LB", "MB", "UB", "SL", "SU"],
                    },
                },
            },
            "BookingRequest": {
                "type": "object",
                "required": ["train_id", "class", "date", "from_seq", "to_seq", "user", "passengers"],
                "properties": {
                    "train_id": {"type": "integer"},
                    "class": {"type": "string", "enum": ["SL", "3A", "2A", "1A"]},
                    "date": {"type": "string", "format": "date"},
                    "from_seq": {"type": "integer"},
                    "to_seq": {"type": "integer"},
                    "quota": {"type": "string", "enum": ["GN", "TQ"]},
                    "user": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "email": {"type": "string"},
                            "phone": {"type": "string"},
                        },
                    },
                    "passengers": {
                        "type": "array",
                        "items": {"$ref": "#/components/schemas/Passenger"},
                    },
                },
            },
            "BookingResponse": {
                "type": "object",
                "properties": {
                    "pnr": {"type": "string"},
                    "status": {"type": "string", "enum": ["confirmed", "rac", "waiting"]},
                    "queue_position": {"type": "integer", "nullable": True},
                },
            },
        },
    },
    "paths": {
        "/api/stations": {
            "get": {
                "summary": "Station autocomplete",
                "parameters": [
                    {"name": "q", "in": "query", "schema": {"type": "string"}}
                ],
                "responses": {"200": {"description": "Matching stations"}},
            }
        },
        "/api/trains": {
            "get": {
                "summary": "List trains",
                "responses": {"200": {"description": "All trains"}},
            }
        },
        "/api/search": {
            "get": {
                "summary": "Trains between two cities",
                "parameters": [
                    {"name": "from", "in": "query", "required": True, "schema": {"type": "string"}},
                    {"name": "to", "in": "query", "required": True, "schema": {"type": "string"}},
                ],
                "responses": {
                    "200": {"description": "Matching journeys"},
                    "400": {"description": "Missing query parameters"},
                },
            }
        },
        "/api/availability": {
            "get": {
                "summary": "Seat availability and fare for a leg",
                "parameters": [
                    {"name": "train_id", "in": "query", "required": True, "schema": {"type": "integer"}},
                    {"name": "cls", "in": "query", "required": True, "schema": {"type": "string"}},
                    {"name": "date", "in": "query", "required": True, "schema": {"type": "string", "format": "date"}},
                    {"name": "from_seq", "in": "query", "required": True, "schema": {"type": "integer"}},
                    {"name": "to_seq", "in": "query", "required": True, "schema": {"type": "integer"}},
                    {"name": "quota", "in": "query", "schema": {"type": "string", "enum": ["GN", "TQ"]}},
                ],
                "responses": {"200": {"description": "Availability payload"}},
            }
        },
        "/api/seatmap": {
            "get": {
                "summary": "Seat-level map for a coach/class",
                "responses": {"200": {"description": "Seats and their status"}},
            }
        },
        "/api/book": {
            "post": {
                "summary": "Create a booking",
                "security": [{"ApiToken": []}],
                "requestBody": {
                    "required": True,
                    "content": {
                        "application/json": {
                            "schema": {"$ref": "#/components/schemas/BookingRequest"}
                        }
                    },
                },
                "responses": {
                    "201": {
                        "description": "Booked",
                        "content": {
                            "application/json": {
                                "schema": {"$ref": "#/components/schemas/BookingResponse"}
                            }
                        },
                    },
                    "400": {"description": "Validation error"},
                    "401": {"description": "Missing or invalid token"},
                    "429": {"description": "Rate limit exceeded"},
                },
            }
        },
        "/api/book-round-trip": {
            "post": {
                "summary": "Create an outbound + return booking",
                "security": [{"ApiToken": []}],
                "responses": {"201": {"description": "Both legs booked"}},
            }
        },
        "/api/pnr/{pnr}": {
            "get": {
                "summary": "Fetch a booking by PNR",
                "parameters": [
                    {"name": "pnr", "in": "path", "required": True, "schema": {"type": "string"}}
                ],
                "responses": {
                    "200": {"description": "Booking record"},
                    "404": {"description": "Unknown PNR"},
                },
            }
        },
        "/api/cancel/{pnr}": {
            "post": {
                "summary": "Cancel a booking",
                "security": [{"ApiToken": []}],
                "parameters": [
                    {"name": "pnr", "in": "path", "required": True, "schema": {"type": "string"}}
                ],
                "responses": {"200": {"description": "Cancelled with refund"}},
            }
        },
    },
}

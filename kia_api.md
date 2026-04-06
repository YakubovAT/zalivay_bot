, а ищ {
  "openapi": "3.0.0",
  "info": {
    "title": "Kie.ai Mock",
    "version": "1.0.0",
    "description": ""
  },
  "servers": [
    {
      "url": ""
    }
  ],
  "paths": {
    "/api/v1/jobs/createTask": {
      "post": {
        "summary": "video generation",
        "responses": {
          "200": {
            "description": "200"
          },
          "401": {
            "description": "401"
          },
          "402": {
            "description": "402"
          },
          "422": {
            "description": "422"
          },
          "429": {
            "description": "429"
          },
          "500": {
            "description": "500"
          }
        },
        "requestBody": {
          "content": {
            "application/json": {
              "schema": {
                "type": "object",
                "properties": {
                  "model": {
                    "type": "string"
                  },
                  "callBackUrl": {
                    "type": "string",
                    "format": "uri"
                  },
                  "input": {
                    "type": "object",
                    "properties": {
                      "prompt": {
                        "type": "string"
                      },
                      "image_urls": {
                        "type": "array",
                        "items": {
                          "type": "string",
                          "format": "uri"
                        }
                      },
                      "aspect_ratio": {
                        "type": "string"
                      },
                      "n_frames": {
                        "type": "string",
                        "format": "utc-millisec"
                      },
                      "remove_watermark": {
                        "type": "boolean"
                      },
                      "upload_method": {
                        "type": "string"
                      }
                    }
                  }
                }
              },
              "example": {
                "model": "sora-2-image-to-video",
                "callBackUrl": "https://your-domain.com/api/callback",
                "input": {
                  "prompt": "A beautiful sunset over the ocean",
                  "image_urls": [
                    "https://example.com/input-image.jpg"
                  ],
                  "aspect_ratio": "landscape",
                  "n_frames": "10",
                  "remove_watermark": true,
                  "upload_method": "s3"
                }
              }
            }
          }
        }
      }
    },
    "/api/v1/jobs/recordInfo": {
      "get": {
        "summary": "task status",
        "parameters": [
          {
            "in": "query",
            "name": "taskId",
            "required": true,
            "schema": { "type": "string" }
          }
        ],
        "responses": {
          "200": {
            "description": "200 completed"
          },
          "401": {
            "description": "401"
          },
          "402": {
            "description": "402"
          },
          "429": {
            "description": "429"
          }
        },
        "security": [
          {
            "BearerAuth": []
          }
        ]
      }
    },
    "/gpt-5-2/v1/chat/completions": {
      "post": {
        "summary": "chat completions",
        "responses": {
          "200": {
            "description": "200"
          },
          "401": {
            "description": "401"
          },
          "402": {
            "description": "402"
          },
          "422": {
            "description": "422"
          },
          "429": {
            "description": "429"
          },
          "500": {
            "description": "500"
          }
        },
        "security": [
          {
            "BearerAuth": []
          }
        ],
        "requestBody": {
          "content": {
            "application/json": {
              "schema": {
                "type": "object",
                "properties": {
                  "model": {
                    "type": "string"
                  },
                  "messages": {
                    "type": "array",
                    "items": {
                      "type": "object",
                      "properties": {
                        "role": {
                          "type": "string"
                        },
                        "content": {
                          "type": "string"
                        }
                      }
                    }
                  }
                }
              },
              "example": {
                "model": "gpt-5-2",
                "messages": [
                  {
                    "role": "user",
                    "content": "Hello"
                  }
                ]
              }
            }
          }
        }
      }
    }
  },
  "components": {
    "securitySchemes": {
      "BearerAuth": {
        "type": "http",
        "scheme": "bearer"
      }
    }
  }
}
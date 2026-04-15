# Instagram Comments, Replies and Subscribers Scraper (No Cookie) (`datadoping/instagram-comments-and-replies-scraper`) Actor

This scraper will help you scrape comments without the need of cookie or your session id.

It is able to scrape replies from all users (not just owner's reply).

It is able to scrape subscribers if there badge is turned on.

This is a paid scraper so scraping is limited for freemium users.

- **URL**: https://apify.com/datadoping/instagram-comments-and-replies-scraper.md
- **Developed by:** [Data Doping](https://apify.com/datadoping) (community)
- **Categories:** Social media, Lead generation, Automation
- **Stats:** 301 total users, 51 monthly users, 100.0% runs succeeded, 13 bookmarks
- **User rating**: 3.94 out of 5 stars

## Pricing

from $1.20 / 1,000 comments

This Actor is paid per event. You are not charged for the Apify platform usage, but only a fixed price for specific events.
Since this Actor supports Apify Store discounts, the price gets lower the higher subscription plan you have.

Learn more: https://docs.apify.com/platform/actors/running/actors-in-store#pay-per-event

## What's an Apify Actor?

Actors are a software tools running on the Apify platform, for all kinds of web data extraction and automation use cases.
In Batch mode, an Actor accepts a well-defined JSON input, performs an action which can take anything from a few seconds to a few hours,
and optionally produces a well-defined JSON output, datasets with results, or files in key-value store.
In Standby mode, an Actor provides a web server which can be used as a website, API, or an MCP server.
Actors are written with capital "A".

## How to integrate an Actor?

If asked about integration, you help developers integrate Actors into their projects.
You adapt to their stack and deliver integrations that are safe, well-documented, and production-ready.
The best way to integrate Actors is as follows.

In JavaScript/TypeScript projects, use official [JavaScript/TypeScript client](https://docs.apify.com/api/client/js.md):

```bash
npm install apify-client
```

In Python projects, use official [Python client library](https://docs.apify.com/api/client/python.md):

```bash
pip install apify-client
```

In shell scripts, use [Apify CLI](https://docs.apify.com/cli/docs.md):

````bash
# MacOS / Linux
curl -fsSL https://apify.com/install-cli.sh | bash
# Windows
irm https://apify.com/install-cli.ps1 | iex
```bash

In AI frameworks, you might use the [Apify MCP server](https://docs.apify.com/platform/integrations/mcp.md).

If your project is in a different language, use the [REST API](https://docs.apify.com/api/v2.md).

For usage examples, see the [API](#api) section below.

For more details, see Apify documentation as [Markdown index](https://docs.apify.com/llms.txt) and [Markdown full-text](https://docs.apify.com/llms-full.txt).


# README

## ?? Instagram Comments & Replies Scraper (No Cookie)

Scrape **Instagram post comments and replies** at lightning speed—**no cookies or session IDs required**.  
This scraper is designed for developers, marketers, and analysts who need reliable and **large-scale comment data** without the hassle of authentication.

---

### ? Features

- ?? **No Cookie or Session ID Required** – Works entirely without logging in.  
- ? **Fast & Scalable** – Scrapes **up to 10,000 comments** per post with optional replies.  
- ?? **Smart Sorting** – Sort comments by "recent" or "popular" to get the most relevant data.  
- ?? **Replies Support** – Optionally scrape replies to comments for complete conversation threads.  
- ?? **Market-Leading Performance** – Efficient rate limiting and concurrent processing for maximum speed.  
- ?? **Structured Output** – Clean, developer-friendly JSON data with all comment metadata.

---

### ?? Example Output

```json
{
  "profile_pic_url": "https://example.jpg",
  "content_type": "comment",
  "text": "Amazing post! ??",
  "like_count": 15,
  "comment_id": "1234567890",
  "username": "john_doe",
  "user_id": "9876543210",
  "created_at_utc": "2024-01-15T10:30:00.000Z",
  "input_url": "https://www.instagram.com/p/abc/",
  ...other data
}
````

***

### ?? Ethical Use Notice

We prioritize responsible and ethical scraping. This scraper does **not** extract private or sensitive user data—such as emails, gender, location, or content hidden behind logins or permissions. It only collects publicly visible information that users have chosen to share on their profiles. Always comply with Instagram’s TOS and local data privacy laws when using this tool.

# Actor input Schema

## `code_or_id_or_url` (type: `array`):

Instagram post codes, IDs, or URLs to scrape. Prefilled with a sample URL.

## `sort_by` (type: `string`):

Choose how to sort the comments before scraping.

## `max_comments` (type: `integer`):

Maximum number of comments to scrape for each post.

## `scrape_replies` (type: `boolean`):

Replies scraping is disabled by default. This setting is ignored by the actor even if changed.

## `max_replies` (type: `integer`):

Maximum number of replies to fetch per comment. This is fixed at 20 if scrape\_replies is disabled.

## Actor input object example

```json
{
  "code_or_id_or_url": [
    "https://www.instagram.com/p/DLm63qQpxvw/"
  ],
  "sort_by": "popular",
  "max_comments": 100,
  "max_replies": 20
}
```

# API

You can run this Actor programmatically using our API. Below are code examples in JavaScript, Python, and CLI, as well as the OpenAPI specification and MCP server setup.

## JavaScript example

```javascript
import { ApifyClient } from 'apify-client';

// Initialize the ApifyClient with your Apify API token
// Replace the '<YOUR_API_TOKEN>' with your token
const client = new ApifyClient({
    token: '<YOUR_API_TOKEN>',
});

// Prepare Actor input
const input = {
    "code_or_id_or_url": [
        "https://www.instagram.com/p/DLm63qQpxvw/"
    ],
    "sort_by": "popular",
    "max_comments": 100,
    "scrape_replies": false,
    "max_replies": 20
};

// Run the Actor and wait for it to finish
const run = await client.actor("datadoping/instagram-comments-and-replies-scraper").call(input);

// Fetch and print Actor results from the run's dataset (if any)
console.log('Results from dataset');
console.log(`?? Check your data here: https://console.apify.com/storage/datasets/${run.defaultDatasetId}`);
const { items } = await client.dataset(run.defaultDatasetId).listItems();
items.forEach((item) => {
    console.dir(item);
});

// ?? Want to learn more ??? Go to ? https://docs.apify.com/api/client/js/docs

```

## Python example

```python
from apify_client import ApifyClient

# Initialize the ApifyClient with your Apify API token
# Replace '<YOUR_API_TOKEN>' with your token.
client = ApifyClient("<YOUR_API_TOKEN>")

# Prepare the Actor input
run_input = {
    "code_or_id_or_url": ["https://www.instagram.com/p/DLm63qQpxvw/"],
    "sort_by": "popular",
    "max_comments": 100,
    "scrape_replies": False,
    "max_replies": 20,
}

# Run the Actor and wait for it to finish
run = client.actor("datadoping/instagram-comments-and-replies-scraper").call(run_input=run_input)

# Fetch and print Actor results from the run's dataset (if there are any)
print("?? Check your data here: https://console.apify.com/storage/datasets/" + run["defaultDatasetId"])
for item in client.dataset(run["defaultDatasetId"]).iterate_items():
    print(item)

# ?? Want to learn more ??? Go to ? https://docs.apify.com/api/client/python/docs/quick-start

```

## CLI example

```bash
echo '{
  "code_or_id_or_url": [
    "https://www.instagram.com/p/DLm63qQpxvw/"
  ],
  "sort_by": "popular",
  "max_comments": 100,
  "scrape_replies": false,
  "max_replies": 20
}' |
apify call datadoping/instagram-comments-and-replies-scraper --silent --output-dataset

```

## MCP server setup

```json
{
    "mcpServers": {
        "apify": {
            "command": "npx",
            "args": [
                "mcp-remote",
                "https://mcp.apify.com/?tools=datadoping/instagram-comments-and-replies-scraper",
                "--header",
                "Authorization: Bearer <YOUR_API_TOKEN>"
            ]
        }
    }
}

```

## OpenAPI specification

```json
{
    "openapi": "3.0.1",
    "info": {
        "title": "Instagram Comments, Replies and Subscribers Scraper (No Cookie)",
        "description": "This scraper will help you scrape comments without the need of cookie or your session id.\n\nIt is able to scrape replies from all users (not just owner's reply).\n\nIt is able to scrape subscribers if there badge is turned on.\n\nThis is a paid scraper so scraping is limited for freemium users.",
        "version": "0.0",
        "x-build-id": "obYekAHh3RLGbnNNR"
    },
    "servers": [
        {
            "url": "https://api.apify.com/v2"
        }
    ],
    "paths": {
        "/acts/datadoping~instagram-comments-and-replies-scraper/run-sync-get-dataset-items": {
            "post": {
                "operationId": "run-sync-get-dataset-items-datadoping-instagram-comments-and-replies-scraper",
                "x-openai-isConsequential": false,
                "summary": "Executes an Actor, waits for its completion, and returns Actor's dataset items in response.",
                "tags": [
                    "Run Actor"
                ],
                "requestBody": {
                    "required": true,
                    "content": {
                        "application/json": {
                            "schema": {
                                "$ref": "#/components/schemas/inputSchema"
                            }
                        }
                    }
                },
                "parameters": [
                    {
                        "name": "token",
                        "in": "query",
                        "required": true,
                        "schema": {
                            "type": "string"
                        },
                        "description": "Enter your Apify token here"
                    }
                ],
                "responses": {
                    "200": {
                        "description": "OK"
                    }
                }
            }
        },
        "/acts/datadoping~instagram-comments-and-replies-scraper/runs": {
            "post": {
                "operationId": "runs-sync-datadoping-instagram-comments-and-replies-scraper",
                "x-openai-isConsequential": false,
                "summary": "Executes an Actor and returns information about the initiated run in response.",
                "tags": [
                    "Run Actor"
                ],
                "requestBody": {
                    "required": true,
                    "content": {
                        "application/json": {
                            "schema": {
                                "$ref": "#/components/schemas/inputSchema"
                            }
                        }
                    }
                },
                "parameters": [
                    {
                        "name": "token",
                        "in": "query",
                        "required": true,
                        "schema": {
                            "type": "string"
                        },
                        "description": "Enter your Apify token here"
                    }
                ],
                "responses": {
                    "200": {
                        "description": "OK",
                        "content": {
                            "application/json": {
                                "schema": {
                                    "$ref": "#/components/schemas/runsResponseSchema"
                                }
                            }
                        }
                    }
                }
            }
        },
        "/acts/datadoping~instagram-comments-and-replies-scraper/run-sync": {
            "post": {
                "operationId": "run-sync-datadoping-instagram-comments-and-replies-scraper",
                "x-openai-isConsequential": false,
                "summary": "Executes an Actor, waits for completion, and returns the OUTPUT from Key-value store in response.",
                "tags": [
                    "Run Actor"
                ],
                "requestBody": {
                    "required": true,
                    "content": {
                        "application/json": {
                            "schema": {
                                "$ref": "#/components/schemas/inputSchema"
                            }
                        }
                    }
                },
                "parameters": [
                    {
                        "name": "token",
                        "in": "query",
                        "required": true,
                        "schema": {
                            "type": "string"
                        },
                        "description": "Enter your Apify token here"
                    }
                ],
                "responses": {
                    "200": {
                        "description": "OK"
                    }
                }
            }
        }
    },
    "components": {
        "schemas": {
            "inputSchema": {
                "type": "object",
                "required": [
                    "code_or_id_or_url"
                ],
                "properties": {
                    "code_or_id_or_url": {
                        "title": "Post Code/ID/URL",
                        "type": "array",
                        "description": "Instagram post codes, IDs, or URLs to scrape. Prefilled with a sample URL.",
                        "items": {
                            "type": "string"
                        }
                    },
                    "sort_by": {
                        "title": "Sort By",
                        "enum": [
                            "recent",
                            "popular"
                        ],
                        "type": "string",
                        "description": "Choose how to sort the comments before scraping."
                    },
                    "max_comments": {
                        "title": "Max Comments per Post",
                        "minimum": 1,
                        "maximum": 10000,
                        "type": "integer",
                        "description": "Maximum number of comments to scrape for each post."
                    },
                    "scrape_replies": {
                        "title": "Scrape Replies",
                        "type": "boolean",
                        "description": "Replies scraping is disabled by default. This setting is ignored by the actor even if changed."
                    },
                    "max_replies": {
                        "title": "Max Replies per Comment",
                        "minimum": 1,
                        "maximum": 1000,
                        "type": "integer",
                        "description": "Maximum number of replies to fetch per comment. This is fixed at 20 if scrape_replies is disabled."
                    }
                }
            },
            "runsResponseSchema": {
                "type": "object",
                "properties": {
                    "data": {
                        "type": "object",
                        "properties": {
                            "id": {
                                "type": "string"
                            },
                            "actId": {
                                "type": "string"
                            },
                            "userId": {
                                "type": "string"
                            },
                            "startedAt": {
                                "type": "string",
                                "format": "date-time",
                                "example": "2025-01-08T00:00:00.000Z"
                            },
                            "finishedAt": {
                                "type": "string",
                                "format": "date-time",
                                "example": "2025-01-08T00:00:00.000Z"
                            },
                            "status": {
                                "type": "string",
                                "example": "READY"
                            },
                            "meta": {
                                "type": "object",
                                "properties": {
                                    "origin": {
                                        "type": "string",
                                        "example": "API"
                                    },
                                    "userAgent": {
                                        "type": "string"
                                    }
                                }
                            },
                            "stats": {
                                "type": "object",
                                "properties": {
                                    "inputBodyLen": {
                                        "type": "integer",
                                        "example": 2000
                                    },
                                    "rebootCount": {
                                        "type": "integer",
                                        "example": 0
                                    },
                                    "restartCount": {
                                        "type": "integer",
                                        "example": 0
                                    },
                                    "resurrectCount": {
                                        "type": "integer",
                                        "example": 0
                                    },
                                    "computeUnits": {
                                        "type": "integer",
                                        "example": 0
                                    }
                                }
                            },
                            "options": {
                                "type": "object",
                                "properties": {
                                    "build": {
                                        "type": "string",
                                        "example": "latest"
                                    },
                                    "timeoutSecs": {
                                        "type": "integer",
                                        "example": 300
                                    },
                                    "memoryMbytes": {
                                        "type": "integer",
                                        "example": 1024
                                    },
                                    "diskMbytes": {
                                        "type": "integer",
                                        "example": 2048
                                    }
                                }
                            },
                            "buildId": {
                                "type": "string"
                            },
                            "defaultKeyValueStoreId": {
                                "type": "string"
                            },
                            "defaultDatasetId": {
                                "type": "string"
                            },
                            "defaultRequestQueueId": {
                                "type": "string"
                            },
                            "buildNumber": {
                                "type": "string",
                                "example": "1.0.0"
                            },
                            "containerUrl": {
                                "type": "string"
                            },
                            "usage": {
                                "type": "object",
                                "properties": {
                                    "ACTOR_COMPUTE_UNITS": {
                                        "type": "integer",
                                        "example": 0
                                    },
                                    "DATASET_READS": {
                                        "type": "integer",
                                        "example": 0
                                    },
                                    "DATASET_WRITES": {
                                        "type": "integer",
                                        "example": 0
                                    },
                                    "KEY_VALUE_STORE_READS": {
                                        "type": "integer",
                                        "example": 0
                                    },
                                    "KEY_VALUE_STORE_WRITES": {
                                        "type": "integer",
                                        "example": 1
                                    },
                                    "KEY_VALUE_STORE_LISTS": {
                                        "type": "integer",
                                        "example": 0
                                    },
                                    "REQUEST_QUEUE_READS": {
                                        "type": "integer",
                                        "example": 0
                                    },
                                    "REQUEST_QUEUE_WRITES": {
                                        "type": "integer",
                                        "example": 0
                                    },
                                    "DATA_TRANSFER_INTERNAL_GBYTES": {
                                        "type": "integer",
                                        "example": 0
                                    },
                                    "DATA_TRANSFER_EXTERNAL_GBYTES": {
                                        "type": "integer",
                                        "example": 0
                                    },
                                    "PROXY_RESIDENTIAL_TRANSFER_GBYTES": {
                                        "type": "integer",
                                        "example": 0
                                    },
                                    "PROXY_SERPS": {
                                        "type": "integer",
                                        "example": 0
                                    }
                                }
                            },
                            "usageTotalUsd": {
                                "type": "number",
                                "example": 0.00005
                            },
                            "usageUsd": {
                                "type": "object",
                                "properties": {
                                    "ACTOR_COMPUTE_UNITS": {
                                        "type": "integer",
                                        "example": 0
                                    },
                                    "DATASET_READS": {
                                        "type": "integer",
                                        "example": 0
                                    },
                                    "DATASET_WRITES": {
                                        "type": "integer",
                                        "example": 0
                                    },
                                    "KEY_VALUE_STORE_READS": {
                                        "type": "integer",
                                        "example": 0
                                    },
                                    "KEY_VALUE_STORE_WRITES": {
                                        "type": "number",
                                        "example": 0.00005
                                    },
                                    "KEY_VALUE_STORE_LISTS": {
                                        "type": "integer",
                                        "example": 0
                                    },
                                    "REQUEST_QUEUE_READS": {
                                        "type": "integer",
                                        "example": 0
                                    },
                                    "REQUEST_QUEUE_WRITES": {
                                        "type": "integer",
                                        "example": 0
                                    },
                                    "DATA_TRANSFER_INTERNAL_GBYTES": {
                                        "type": "integer",
                                        "example": 0
                                    },
                                    "DATA_TRANSFER_EXTERNAL_GBYTES": {
                                        "type": "integer",
                                        "example": 0
                                    },
                                    "PROXY_RESIDENTIAL_TRANSFER_GBYTES": {
                                        "type": "integer",
                                        "example": 0
                                    },
                                    "PROXY_SERPS": {
                                        "type": "integer",
                                        "example": 0
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}
```


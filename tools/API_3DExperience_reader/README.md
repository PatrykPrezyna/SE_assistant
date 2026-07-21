# 3DEXPERIENCE starter example

This folder contains a very small Python example you can use as a starting point for connecting to a 3DEXPERIENCE tenant and reading a REST resource.

## What it does

The script sends a simple GET request to a resource URL and prints the response. It is intentionally generic so you can adapt it to your deployment.

## Quick start

Run it from the repository root:

```cmd
python tools/API_3DExperience_reader/simple_example.py --base-url https://your-tenant.3dexperience.3ds.com --resource-url /resources/v1/people/me --username your-user --password your-password
```

You can also set environment variables instead of passing CLI arguments:

```cmd
set THREEDX_BASE_URL=https://your-tenant.3dexperience.3ds.com
set THREEDX_RESOURCE_URL=/resources/v1/people/me
set THREEDX_USERNAME=your-user
set THREEDX_PASSWORD=your-password
python tools/API_3DExperience_reader/simple_example.py
```

## How to adapt it

- Replace the resource URL with the endpoint that returns the information you want, for example a CAD object, a product, or a Modelica artifact metadata endpoint.
- If your tenant uses SSO, OAuth, or a session cookie instead of basic authentication, swap out the auth code in the script.
- If you do not know the exact endpoint yet, start with a safe read-only endpoint in your environment and confirm it returns JSON.

## Notes

3DEXPERIENCE deployments differ a lot between customers. The exact URL pattern, authentication method, and response format depend on your tenant and installed modules.

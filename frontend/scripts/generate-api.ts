import { generate } from 'openapi-typescript-codegen';

// Generate API client
generate({
    input: 'http://localhost:8080/openapi.json',
    output: './src/api',
    client: 'react-query',
    httpClient: 'fetch'
});
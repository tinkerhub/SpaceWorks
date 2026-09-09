import { configuredApiUrl } from "./runtimeConfig";

export const API_URL = configuredApiUrl();

export const API_V1_URL = API_URL.replace(/\/api$/, "/api/v1");

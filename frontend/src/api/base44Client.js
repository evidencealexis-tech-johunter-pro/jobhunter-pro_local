const API_BASE = "/api";

let csrfToken = null;

async function parseResponse(response) {
  const contentType =
    response.headers.get("content-type") || "";

  const data = contentType.includes("application/json")
    ? await response.json()
    : await response.text();

  if (!response.ok) {
    const message =
      typeof data === "string"
        ? data
        : data?.detail ||
          data?.message ||
          `Request failed with status ${response.status}`;

    const error = new Error(message);
    error.status = response.status;
    error.data = data;
    throw error;
  }

  return data;
}

async function getCsrfToken() {
  if (csrfToken) {
    return csrfToken;
  }

  const response = await fetch(
    `${API_BASE}/apps/local/auth/csrf`,
    {
      method: "GET",
      credentials: "include",
      headers: {
        Accept: "application/json",
      },
    }
  );

  const data = await parseResponse(response);

  csrfToken = data?.csrf_token || null;

  if (!csrfToken) {
    throw new Error("Unable to obtain CSRF token.");
  }

  return csrfToken;
}

export async function request(
  path,
  {
    method = "GET",
    body,
    headers = {},
    requiresCsrf = false,
  } = {}
) {
  const upperMethod = method.toUpperCase();

  const requestHeaders = {
    Accept: "application/json",
    ...headers,
  };

  if (body !== undefined) {
    requestHeaders["Content-Type"] =
      "application/json";
  }

  if (
    requiresCsrf &&
    !["GET", "HEAD", "OPTIONS"].includes(
      upperMethod
    )
  ) {
    requestHeaders["X-CSRF-Token"] =
      await getCsrfToken();
  }

  const response = await fetch(
    `${API_BASE}${path}`,
    {
      method: upperMethod,
      credentials: "include",
      headers: requestHeaders,
      body:
        body === undefined
          ? undefined
          : JSON.stringify(body),
    }
  );

  return parseResponse(response);
}

function buildQuery({
  filters,
  sort,
  limit,
} = {}) {
  const params = new URLSearchParams();

  if (
    filters &&
    Object.keys(filters).length > 0
  ) {
    params.set(
      "q",
      JSON.stringify(filters)
    );
  }

  if (sort) {
    params.set("sort", sort);
  }

  if (limit !== undefined && limit !== null) {
    params.set("limit", String(limit));
  }

  const query = params.toString();

  return query ? `?${query}` : "";
}

function createEntityApi(entityName) {
  const basePath =
    `/apps/local/entities/${encodeURIComponent(
      entityName
    )}`;

  return {
    async list(sort, limit) {
      return request(
        `${basePath}${buildQuery({
          sort,
          limit,
        })}`
      );
    },

    async filter(filters = {}, sort, limit) {
      return request(
        `${basePath}${buildQuery({
          filters,
          sort,
          limit,
        })}`
      );
    },

    async create(data) {
      return request(basePath, {
        method: "POST",
        body: data,
        requiresCsrf: true,
      });
    },

    async update(id, data) {
      return request(
        `${basePath}/${encodeURIComponent(id)}`,
        {
          method: "PATCH",
          body: data,
          requiresCsrf: true,
        }
      );
    },

    async delete(id) {
      return request(
        `${basePath}/${encodeURIComponent(id)}`,
        {
          method: "DELETE",
          requiresCsrf: true,
        }
      );
    },
  };
}

const entityNames = [
  "Resume",
  "Job",
  "ScrapeSource",
  "ContextDocument",
  "AppSettings",
  "UserApiKey",
  "ScrapeJob",
  "Notification",
];

const entities = Object.fromEntries(
  entityNames.map((entityName) => [
    entityName,
    createEntityApi(entityName),
  ])
);

const integrations = {
  Core: {
    async InvokeLLM({
      prompt,
      response_json_schema,
      file_urls,
    }) {
      return request(
        "/apps/local/integration-endpoints/Core/InvokeLLM",
        {
          method: "POST",
          requiresCsrf: true,
          body: {
            prompt,
            response_json_schema:
              response_json_schema || null,
            file_urls: file_urls || [],
          },
        }
      );
    },

    async UploadFile({ file }) {
      const formData = new FormData();
      formData.append("file", file);

      const token = await getCsrfToken();

      const response = await fetch(
        `${API_BASE}/apps/local/integration-endpoints/Core/UploadFile`,
        {
          method: "POST",
          credentials: "include",
          headers: {
            Accept: "application/json",
            "X-CSRF-Token": token,
          },
          body: formData,
        }
      );

      return parseResponse(response);
    },
  },
};

export const base44 = {
  entities,
  integrations,
};
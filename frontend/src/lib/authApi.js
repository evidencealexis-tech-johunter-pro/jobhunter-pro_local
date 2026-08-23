const API = "/api";

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

let csrfToken = null;

async function getCsrfToken() {
  if (csrfToken) {
    return csrfToken;
  }

  const response = await fetch(
    `${API}/apps/local/auth/csrf`,
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

export function clearCsrfToken() {
  csrfToken = null;
}

async function post(
  path,
  body,
  requiresCsrf = false
) {
  const headers = {
    Accept: "application/json",
    "Content-Type": "application/json",
  };

  if (requiresCsrf) {
    headers["X-CSRF-Token"] = await getCsrfToken();
  }

  const response = await fetch(
    `${API}${path}`,
    {
      method: "POST",
      credentials: "include",
      headers,
      body: JSON.stringify(body),
    }
  );

  if (
    response.status === 403 &&
    requiresCsrf
  ) {
    csrfToken = null;

    headers["X-CSRF-Token"] =
      await getCsrfToken();

    const retry = await fetch(
      `${API}${path}`,
      {
        method: "POST",
        credentials: "include",
        headers,
        body: JSON.stringify(body),
      }
    );

    return parseResponse(retry);
  }

  return parseResponse(response);
}

export async function login(email, password) {
  const result = await post(
    "/apps/local/auth/login",
    {
      email,
      password,
    }
  );

  clearCsrfToken();

  return result;
}

export async function signup(email, password) {
  const result = await post(
    "/apps/local/auth/signup",
    {
      email,
      password,
    }
  );

  clearCsrfToken();

  return result;
}

export async function requestPasswordReset(
  email
) {
  return post(
    "/apps/local/auth/password-reset/request",
    {
      email,
    }
  );
}

export async function confirmPasswordReset(
  resetToken,
  newPassword
) {
  return post(
    "/apps/local/auth/password-reset/confirm",
    {
      resetToken,
      newPassword,
    }
  );
}

export async function logout() {
  try {
    return await post(
      "/apps/auth/logout",
      {},
      true
    );
  } finally {
    clearCsrfToken();
  }
}

export async function getCurrentUser() {
  const response = await fetch(
    `${API}/apps/local/entities/User/me`,
    {
      method: "GET",
      credentials: "include",
      headers: {
        Accept: "application/json",
      },
    }
  );

  return parseResponse(response);
}
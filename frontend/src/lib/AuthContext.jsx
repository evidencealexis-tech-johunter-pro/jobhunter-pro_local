import React, {
  createContext,
  useContext,
  useEffect,
  useState,
} from "react";

const AuthContext = createContext(null);

const PUBLIC_SETTINGS_ENDPOINT =
  "/api/apps/public/prod/public-settings/by-id/local";

const CURRENT_USER_ENDPOINT =
  "/api/apps/local/entities/User/me";

const CSRF_ENDPOINT =
  "/api/apps/local/auth/csrf";

const LOGOUT_ENDPOINT =
  "/api/apps/auth/logout";

let csrfToken = null;

async function parseResponse(response) {
  const contentType =
    response.headers.get("content-type") || "";

  let data = null;

  if (contentType.includes("application/json")) {
    data = await response.json();
  } else {
    const text = await response.text();
    data = text || null;
  }

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
    CSRF_ENDPOINT,
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

function clearCsrfToken() {
  csrfToken = null;
}

async function fetchCurrentUser() {
  const response = await fetch(
    CURRENT_USER_ENDPOINT,
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

async function fetchPublicSettings() {
  const response = await fetch(
    PUBLIC_SETTINGS_ENDPOINT,
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

async function performLogout() {
  const token = await getCsrfToken();

  const response = await fetch(
    LOGOUT_ENDPOINT,
    {
      method: "POST",
      credentials: "include",
      headers: {
        Accept: "application/json",
        "X-CSRF-Token": token,
      },
    }
  );

  try {
    return await parseResponse(response);
  } finally {
    clearCsrfToken();
  }
}

export const AuthProvider = ({ children }) => {
  const [user, setUser] = useState(null);
  const [isAuthenticated, setIsAuthenticated] =
    useState(false);

  const [isLoadingAuth, setIsLoadingAuth] =
    useState(true);

  const [
    isLoadingPublicSettings,
    setIsLoadingPublicSettings,
  ] = useState(true);

  const [authError, setAuthError] =
    useState(null);

  const [authChecked, setAuthChecked] =
    useState(false);

  const [appPublicSettings, setAppPublicSettings] =
    useState(null);

  const checkUserAuth = async () => {
    setIsLoadingAuth(true);
    setAuthError(null);

    try {
      const currentUser =
        await fetchCurrentUser();

      setUser(currentUser);
      setIsAuthenticated(true);
    } catch (error) {
      setUser(null);
      setIsAuthenticated(false);

      if (
        error.status !== 401 &&
        error.status !== 403
      ) {
        console.error(
          "User auth check failed:",
          error
        );
      }

      if (
        error.status === 401 ||
        error.status === 403
      ) {
        setAuthError({
          type: "auth_required",
          message: "Authentication required",
        });
      }
    } finally {
      setIsLoadingAuth(false);
      setAuthChecked(true);
    }
  };

  const checkAppState = async () => {
    setIsLoadingPublicSettings(true);
    setIsLoadingAuth(true);
    setAuthError(null);

    try {
      const publicSettings =
        await fetchPublicSettings();

      setAppPublicSettings(
        publicSettings
      );

      await checkUserAuth();
    } catch (error) {
      console.error(
        "App state check failed:",
        error
      );

      if (
        error.status === 401 ||
        error.status === 403
      ) {
        setAuthError({
          type: "auth_required",
          message: "Authentication required",
        });
      } else {
        setAuthError({
          type: "unknown",
          message:
            error.message ||
            "Failed to load application",
        });
      }

      setIsLoadingAuth(false);
      setAuthChecked(true);
    } finally {
      setIsLoadingPublicSettings(false);
    }
  };

  useEffect(() => {
    checkAppState();
  }, []);

  const logout = async (
    shouldRedirect = true
  ) => {
    try {
      await performLogout();
    } catch (error) {
      // Even if the server-side logout request fails,
      // clear the local authentication state.
      console.error(
        "Logout request failed:",
        error
      );

      clearCsrfToken();
    } finally {
      setUser(null);
      setIsAuthenticated(false);
      setAuthError(null);
      setAuthChecked(true);

      if (shouldRedirect) {
        window.location.assign("/login");
      }
    }
  };

  const navigateToLogin = () => {
    window.location.assign("/login");
  };

  return (
    <AuthContext.Provider
      value={{
        user,
        isAuthenticated,
        isLoadingAuth,
        isLoadingPublicSettings,
        authError,
        appPublicSettings,
        authChecked,
        logout,
        navigateToLogin,
        checkUserAuth,
        checkAppState,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
};

export const useAuth = () => {
  const context = useContext(AuthContext);

  if (!context) {
    throw new Error(
      "useAuth must be used within an AuthProvider"
    );
  }

  return context;
};
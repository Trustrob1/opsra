import axios from "axios";

const API_BASE = "http://localhost:8000/api/v1";

// ⚠️ move this to env later
const SUPERADMIN_SECRET = "uLN0f7pDiTzgy017m7vkN1yjoVlyj6Zn47CGSXIq8NI";

export const createOrganisation = async (payload) => {
  const res = await axios.post(
    `${API_BASE}/superadmin/organisations`,
    payload,
    {
      headers: {
        "Content-Type": "application/json",
        "X-Superadmin-Secret": SUPERADMIN_SECRET,
      },
    }
  );

  return res.data;
};
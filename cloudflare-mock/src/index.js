import fixture from "./test-customers.json";

const customers = fixture.customers;
const CORS = {
  "access-control-allow-origin": "*",
  "access-control-allow-methods": "GET, POST, OPTIONS",
  "access-control-allow-headers": "content-type, authorization, accept",
};

function json(body, status = 200) {
  return Response.json(body, { status, headers: CORS });
}

async function readBody(request) {
  try {
    return await request.json();
  } catch {
    return null;
  }
}

function isTemplateVariable(value) {
  return typeof value === "string" && (value.includes("{{") || value.includes("%7B%7B"));
}

function normalized(value) {
  return String(value ?? "").trim();
}

function makeError(status, code, message, type = "ERROR") {
  const guid = crypto.randomUUID().replaceAll("-", "");
  return json({
    result: {
      guid,
      returnCode: code,
      messageText: message,
      code,
      message,
      type,
      details: { guid, rootCause: null, errorOrigin: "freya-bank-statement-mock" },
    },
  }, status);
}

const errorFor = {
  "cards.list": () => makeError(404, "FB_IVR_CHANNEL_102", "Müşteriye ait geçerli kart bilgisi bulunamadı.", "WARNING"),
  "cards.balance": () => makeError(404, "FB_IVR_CHANNEL_120", "Kart bilgisi bulunamadı.", "WARNING"),
  "statement.week.get": () => makeError(404, "FB_IVR_CHANNEL_121", "Kart bilgisi bulunamadı.", "WARNING"),
  "statement.week.decide": () => makeError(400, "INVALID_ARGUMENTS_ERROR", "Requested card or statement week was not found."),
  "statement.week.change": () => makeError(400, "INVALID_ARGUMENTS_ERROR", "Requested card or statement week was not found."),
  "contact.email.get": () => makeError(400, "INVALID_ARGUMENTS_ERROR", "Customer was not found."),
  "statement.pdf.send": () => makeError(404, "FB_IVR_CHANNEL_107", "Pdf dokümanı bulunamadı", "WARNING"),
};

function requiredFieldError(field) {
  return makeError(400, "INVALID_ARGUMENTS_ERROR", `${field} cannot be empty`);
}

function lookupEntry(customer, service, data) {
  const entries = customer?.services?.[service];
  if (!entries) return undefined;

  if (["cards.list", "contact.email.get", "statement.pdf.send"].includes(service)) {
    return entries;
  }

  let cardNumber = normalized(data.cardNumber);
  if (isTemplateVariable(cardNumber)) {
    cardNumber = Object.keys(entries)[0] ?? "";
  }
  const cardEntry = entries[cardNumber];
  if (!cardEntry) return undefined;

  if (service === "statement.week.decide" || service === "statement.week.change") {
    let week = normalized(data.newStatementWeek);
    if (isTemplateVariable(week) || !week) week = Object.keys(cardEntry)[0] ?? "";
    return cardEntry[week];
  }
  return cardEntry;
}

async function serviceCall(service, request) {
  const body = await readBody(request);
  if (!body || typeof body !== "object" || !body.data || typeof body.data !== "object") {
    return requiredFieldError("data");
  }
  const data = body.data;
  const required = {
    "cards.list": ["customerNo"],
    "cards.balance": ["cardNumber"],
    "statement.week.get": ["cardNumber"],
    "statement.week.decide": ["cardNumber", "newStatementWeek", "statementDay"],
    "statement.week.change": ["cardNumber", "newStatementWeek", "statementDay"],
    "contact.email.get": ["customerNo", "intAddressInfoType"],
    "statement.pdf.send": ["customerNo", "cardNumber", "currencyType", "statementDate", "emailAddress"],
  }[service];

  for (const field of required) {
    const value = data[field];
    if (value === undefined || value === null || value === "") return requiredFieldError(field);
  }

  let customerNo = normalized(data.customerNo);
  if (isTemplateVariable(customerNo)) customerNo = normalized(customers[0]?.customerNo);
  let customer = customerNo
    ? customers.find((item) => normalized(item.customerNo) === customerNo)
    : undefined;
  // The service contract identifies card-level requests by cardNumber; unlike
  // cards.list, these requests do not carry customerNo. Resolve the fixture
  // owner from the full masked card number returned by cards.list.
  if (!customer && !customerNo && data.cardNumber) {
    const cardNumber = normalized(data.cardNumber);
    customer = customers.find((item) =>
      Object.prototype.hasOwnProperty.call(item.services?.[service] ?? {}, cardNumber),
    );
  }
  const entry = lookupEntry(customer, service, data);
  if (!entry || typeof entry.http !== "number" || !entry.response) return errorFor[service]();

  if (entry.delaySeconds > 0) {
    await new Promise((resolve) => setTimeout(resolve, entry.delaySeconds * 1000));
  }
  return json(entry.response, entry.http);
}

const serviceByPath = new Map([
  ["/voice/v1/cards.list", "cards.list"],
  ["/voice/v1/cards.balance", "cards.balance"],
  ["/voice/v1/statement.week.get", "statement.week.get"],
  ["/voice/v1/statement.week.decide", "statement.week.decide"],
  ["/voice/v1/statement.week.change", "statement.week.change"],
  ["/voice/v1/contact.email.get", "contact.email.get"],
  ["/voice/v1/statement.pdf.send", "statement.pdf.send"],
]);

export default {
  async fetch(request) {
    const url = new URL(request.url);
    if (request.method === "OPTIONS") return new Response(null, { headers: CORS });
    if (request.method === "GET" && url.pathname === "/healthz") {
      return json({ status: "ok", service: "freya-bank-statement-mock" });
    }
    if (request.method === "POST" && url.pathname === "/oauth2/token") {
      return json({ access_token: "synthetic-test-token", token_type: "Bearer", expires_in: 1800 });
    }
    const service = serviceByPath.get(url.pathname);
    if (request.method === "POST" && service) return serviceCall(service, request);
    return json({ error: "not_found" }, 404);
  },
};

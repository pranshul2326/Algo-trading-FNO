import { pageFromPath } from "./routes";

document.body.dataset["page"] = pageFromPath(location.pathname);

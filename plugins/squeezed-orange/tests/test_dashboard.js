#!/usr/bin/env node
/* Deterministic checks for the dashboard's own logic. Extracts functions from template.html; no browser, no model calls. */
const fs = require("fs"), path = require("path"), vm = require("vm");
const html = fs.readFileSync(path.join(__dirname, "..", "dashboard", "template.html"), "utf8");
const script = html.slice(html.indexOf("<script>") + 8, html.lastIndexOf("</script>"));
const grab = (re) => { const m = script.match(re); if (!m) throw new Error("missing " + re); return m[0]; };
function fn(name) { const i = script.indexOf("function " + name + "("); if (i < 0) throw new Error("missing function " + name); let d = 0, k = script.indexOf("{", i); for (; k < script.length; k++) { if (script[k] === "{") d++; if (script[k] === "}" && --d === 0) break; } return script.slice(i, k + 1); }
const line = (name) => { const i = script.indexOf("const " + name + "="); if (i < 0) throw new Error("missing const " + name); return script.slice(i, script.indexOf("\n", i)); };
const ctx = { console, S: { settings: { income: { monthly: [], oneTime: [] }, funds: [] }, hist: null, months: {} }, NOW: "2026-11", Math, JSON, Date };
ctx.now = new Date(2026, 10, 24);
vm.createContext(ctx);
vm.runInContext([line("med"), line("DISCRETIONARY"), line("DEFAULT_CATS"), line("parts"), fn("incomeFor"), fn("monthsBetween"), fn("catSpend"), fn("fundBal"), fn("bpSplit"), fn("freshHistory"), fn("setupSteps"), line("hash"), "this.exports={incomeFor,monthsBetween,fundBal,bpSplit,freshHistory,setupSteps,parts,DISCRETIONARY,DEFAULT_CATS}"].join("\n"), ctx);
const X = ctx.exports; let fails = 0;
function t(name, f) { try { f(); console.log("PASS", name); } catch (e) { fails++; console.log("FAIL", name, "-", e.message); } }
const eq = (a, b, m) => { if (JSON.stringify(a) !== JSON.stringify(b)) throw new Error((m || "") + " got " + JSON.stringify(a) + " want " + JSON.stringify(b)); };
t("script_has_no_syntax_errors", () => new vm.Script(script));
t("income_monthly_period", () => { ctx.S.settings.income = { monthly: [{ amount: 100, from: "2026-01", to: "2026-06" }, { amount: 50, from: "2026-07", to: "" }], oneTime: [] }; eq(X.incomeFor("2026-03").total, 100); eq(X.incomeFor("2026-08").total, 50); });
t("income_one_time_single_month", () => { ctx.S.settings.income = { monthly: [], oneTime: [{ amount: 500, date: "2026-11-24" }] }; eq(X.incomeFor("2026-11").total, 500); eq(X.incomeFor("2026-12").total, 0); });
t("income_one_time_spread", () => { ctx.S.settings.income = { monthly: [], oneTime: [{ amount: 1000, date: "2026-11-24", months: 5 }] }; eq(X.incomeFor("2026-11").total, 200); eq(X.incomeFor("2027-03").total, 200); eq(X.incomeFor("2027-04").total, 0); eq(X.incomeFor("2026-10").total, 0); });
t("income_spread_crosses_year", () => { ctx.S.settings.income = { monthly: [], oneTime: [{ amount: 300, date: "2026-12-01", months: 3 }] }; eq(X.incomeFor("2027-02").total, 100); eq(X.incomeFor("2027-03").total, 0); });
t("split_parts_default_and_split", () => { eq(X.parts({ category: "A", amount: 5 }), [{ category: "A", amount: 5 }]); eq(X.parts({ category: "A", amount: 5, splits: [{ category: "A", amount: 2 }, { category: "B", amount: 3 }] }).length, 2); });
t("budget_split_meets_target_and_cap", () => { const rows = [{ name: "Restaurant", base: 400 }, { name: "Grocery", base: 600 }, { name: "Gas", base: 200 }]; const c = X.bpSplit(rows, 300, {}); const tot = Object.values(c).reduce((a, b) => a + b, 0); if (Math.abs(tot - 300) > 1) throw new Error("total " + tot); rows.forEach(r => { if (c[r.name] > r.base * 0.4 + 0.01) throw new Error("cap " + r.name); }); });
t("budget_split_weights_discretionary", () => { const rows = [{ name: "Restaurant", base: 400 }, { name: "Grocery", base: 400 }]; const c = X.bpSplit(rows, 100, {}); if (!(c.Restaurant > c.Grocery)) throw new Error(JSON.stringify(c)); });
t("budget_split_locked_untouched", () => { const rows = [{ name: "Restaurant", base: 400 }, { name: "Grocery", base: 400 }]; const c = X.bpSplit(rows, 100, { Restaurant: 1 }); eq(c.Restaurant, 0); });
t("budget_split_stops_at_capacity", () => { const rows = [{ name: "Gas", base: 100 }]; const c = X.bpSplit(rows, 1000, {}); eq(Math.round(c.Gas), 40); });
t("months_between", () => eq(X.monthsBetween("2026-11", "2027-02"), ["2026-11", "2026-12", "2027-01", "2027-02"]));
t("sinking_fund_balance", () => { ctx.S.hist = { months: ["2026-09", "2026-10"], cats: { Travel: [100, 200] } }; ctx.S.months = { "2026-11": { txns: [{ amount: 50, category: "Travel" }] } }; const b = X.fundBal({ start: "2026-09", monthly: 150, opening: 0, category: "Travel" }); eq([b.set, b.spent, b.bal, b.months], [450, 350, 100, 3]); });
t("fresh_history_is_valid", () => { const h = X.freshHistory(); eq(h.months.length, 12); eq(h.months[11], "2026-10"); Object.values(h.cats).forEach(a => { eq(a.length, 12); eq(a[11], 0); }); eq(h.source, "empty"); });
t("setup_steps_progress", () => { ctx.S = { settings: { income: { monthly: [], oneTime: [] }, extraFixed: [], fixedNow: {}, balances: [], name: "" }, hist: null, sync: null }; const none = X.setupSteps(null).filter(s => s.done).length; ctx.S = { settings: { income: { monthly: [{}], oneTime: [] }, extraFixed: [{}], fixedNow: {}, balances: [{}], name: "Home" }, hist: { source: "sheet", fixedCats: [] }, sync: { lastRun: "x" } }; const some = X.setupSteps({ allTx: [{}] }).filter(s => s.done).length; eq([none, some], [0, 7]); });
process.exit(fails ? 1 : 0);

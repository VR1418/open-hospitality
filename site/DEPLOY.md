# Putting ophosp.com on AWS — start to finish

*Written for someone who has not done this before, and rewritten after doing it
for real in September 2026. AWS had just replaced CloudFront's single form with a
five-step wizard, and that wizard skips two settings the site cannot work
without. Both are covered below, where they bite.*

*Set aside about an hour. Most of it is waiting, and the waiting is longer than
AWS suggests.*

You will end up with:

```
ophosp.com ─┐
            ├─► Route 53 (DNS) ──► CloudFront (HTTPS + CDN) ──► S3 (the files)
www. ───────┘
```

---

## Before you start

You need:

- your AWS account, signed in
- `ophosp.com`, registered wherever you bought it — you change one setting there
- `site/index.html` and `site/favicon.svg` from this repository
- the build zip from `dist/`

**First, a budget.** Search the console for **Billing** → **Budgets** → create one
for $5 with an email alert. The site costs a couple of dollars a month, but the
console has at least two options that cost real money (you will meet them), and a
budget means a mis-click cannot quietly become a bill.

### Regions

The region selector is top-right. Most of this does not care which one you are
in. **The certificate does: it must be requested in N. Virginia (us-east-1).**
CloudFront accepts certificates from nowhere else, and when you get this wrong it
does not say so — the certificate list is simply empty.

---

## Part 1 — The bucket

1. Console search → **S3** → **Create bucket**.
2. **Name:** `ophosp-site`. (Names are global across AWS; if taken, add something.)
3. **Region:** whichever is nearest. Ours is in Ohio; CloudFront caches worldwide
   so it barely matters.
4. **Leave "Block all public access" ticked.** It looks wrong and is not. The
   bucket stays private; CloudFront gets its own key to it, so nobody can go round
   the CDN to the bucket directly.
5. **Create bucket.**

> ✅ `ophosp-site` appears in your bucket list.

## Part 2 — The files

1. Open the bucket → **Upload** → add `index.html` and `favicon.svg` → **Upload**.
2. **Create folder** → `download`.
3. Rename the build zip on your computer to **`Open-Hospitality-Windows.zip`**
   first — no spaces, or the link fills with `%20`. The page already links to
   that name.
4. Open `download` → **Upload** the zip. It is about 115 MB.

> ✅ The bucket holds `index.html`, `favicon.svg` and
> `download/Open-Hospitality-Windows.zip`. Opening any of them directly says
> **Access Denied**. That is correct until CloudFront is in front.

## Part 3 — The certificate

**Region: N. Virginia. Check it now.**

1. Search → **Certificate Manager** → **Request** → **Request a public certificate**.
2. Domain name: `ophosp.com`
3. **Add another name to this certificate:** `www.ophosp.com`
   Do this now even if you do not want `www` yet. Adding it later means a new
   certificate.
4. Validation: **DNS validation** → **Request**.

It says **Pending validation** until Part 4 exists. Leave it.

## Part 4 — DNS in Route 53

The domain stays registered where it is. You are only moving who **answers DNS**
for it, because a bare domain (`ophosp.com`, without `www`) can only point at
CloudFront through an AWS-specific *Alias* record — and most registrars cannot
make one.

1. Search → **Route 53** → **Hosted zones** → **Create hosted zone**.
   Domain `ophosp.com`, **Public** → **Create**.
2. Find the **NS** record and copy its four values
   (`ns-….awsdns-….com`, `.net`, `.org`, `.co.uk`).
3. **At your registrar**, find **Nameservers**, choose custom, paste the four,
   save. Usually minutes; can be a day.
4. Back in **Certificate Manager** (N. Virginia) → the certificate →
   **Create records in Route 53** → confirm.
5. Wait for the certificate to say **Issued**.

> ✅ The hosted zone has **four records**: `NS`, `SOA`, and two `CNAME`s with long
> names starting `_`. **Never delete those two CNAMEs** — they are how the
> certificate renews next year.

> ⚠️ **Use "Hosted zones", not the Route 53 Dashboard.** If your domain is
> registered elsewhere, the Dashboard shows a red *"Route 53 couldn't update the
> page"* banner and *"Domain registration: Error"*. Both come from a summary box
> that lists domains *registered through AWS* — you have none, and it errors
> instead of saying so. It does not affect your DNS at all.

## Part 5 — CloudFront: the five-step wizard

Search → **CloudFront** → **Create distribution**. It is a wizard now:
*Get started → Specify origin → Enable security → Get TLS certificate → Review and create.*

### Step 1 — Get started

- **Distribution name:** `ophosp-site`
- **Distribution type:** *Single website configuration*
- **Route 53 managed domain:** you can try `ophosp.com` with **Check domain**.
  It may decline a domain registered elsewhere; if so, leave it empty and attach
  the domain in the settings afterwards (Part 6).

### Step 2 — Specify origin

- Pick the **`ophosp-site` bucket** as the origin.
- Choose **Origin access control** (not public access, not a website endpoint).
- The wizard offers to update the bucket's policy so CloudFront can read it.
  Let it, or copy the policy it shows into **S3 → bucket → Permissions → Bucket
  policy**.
- **If it offers staging, continuous deployment, or a second copy for testing,
  decline.** See [If you ended up with two distributions](#if-you-ended-up-with-two-distributions).

### Step 3 — Enable security

This offers **AWS WAF**. **It costs money** — several dollars a month plus
per-request charges — and a one-page site with a download does not need it.
Choose the option that does **not** enable protections.

### Step 4 — Get TLS certificate

Choose the certificate from Part 3. If the list is empty: it is in the wrong
region, or not *Issued* yet.

### Step 5 — Review and create

Create it. It deploys for a while — see [Waiting for a deploy](#waiting-for-a-deploy).

## Part 6 — The settings the wizard skips

**Do not skip this part.** Without it the bare domain shows an XML error.

CloudFront → **Distributions** → click your distribution's **ID** → **General** tab
→ **Settings** → **Edit**.

1. **Default root object:** `index.html` (no leading slash).
   *Without it, `https://ophosp.com/` answers `403 AccessDenied` in XML.* CloudFront
   asks S3 for an object with no name; a private bucket will not admit whether
   something exists, so it says "Access Denied" rather than "Not Found". It looks
   like a permissions problem. It is not.
2. **Alternate domain names:** make sure **both** are listed —
   `ophosp.com`, then **Add item** → `www.ophosp.com`.
   *Careful:* **Remove** sits right beside each entry, and it is easy to type
   over the existing name instead of using **Add item**.
3. **Custom SSL certificate:** your `ophosp.com` certificate.

> 🛑 **Leave "Legacy clients support" OFF.** It costs **$600 a month**, for
> browsers from the Windows XP era.

Leave everything else — security policy, HTTP versions, price class, IPv6, Anycast
static IP, mTLS, cache tags. None affect whether the site works.

**Save changes**, then wait for the deploy to finish before Part 7.

## Part 7 — Point the names at CloudFront

**Route 53** → **Hosted zones** → `ophosp.com` → **Create record**.

**The bare domain:**

1. **Record name:** leave **empty**
2. **Record type:** **A**
3. **Alias:** on
4. **Route traffic to:** *Alias to CloudFront distribution* → your distribution
5. **Create records**

**Then `www`** — only after `www.ophosp.com` is an alternate domain name on the
distribution (Part 6) and that change has finished deploying. The other way round,
visitors typing `www` get a certificate warning.

Same five steps, with **Record name: `www`**. The box already shows `.ophosp.com`
after it — type only `www`, or you will create `www.ophosp.com.ophosp.com`.

## Part 8 — Check it

In a browser: `https://ophosp.com`, `https://www.ophosp.com`, and `http://ophosp.com`
(which should jump to `https`). Click **Download for Windows**.

Or, from a terminal, the checks that were used to verify it:

```bash
# does the name point at CloudFront?
nslookup ophosp.com 8.8.8.8

# does the page load, and is it ours?
curl -sS -o /dev/null -w "%{http_code}\n" https://ophosp.com/
curl -sS https://ophosp.com/ | grep -o "<title>[^<]*</title>"

# does http:// redirect?
curl -sS -o /dev/null -w "%{http_code} -> %{redirect_url}\n" http://ophosp.com/

# is the certificate right? (look for subject=CN=ophosp.com)
echo | openssl s_client -connect ophosp.com:443 -servername ophosp.com 2>&1 | grep subject=
```

---

## Waiting for a deploy

Every change to a distribution deploys to CloudFront's edge locations region by
region. **It can take well over ten minutes** — longer than the console implies.

**Watch the deployment status, not the "Last modified" time.** The time updates
the moment you save; the distribution can still be *Deploying* long after.

While it deploys, some or all visitors can see things that look like new
problems. They are not:

| During a deploy you may see | What it is |
|---|---|
| Browser: *"This site can't provide a secure connection"*, or `curl: (35) … SEC_E_ILLEGAL_MESSAGE` | Edges briefly lack the certificate for your name. `openssl` shows `alert number 40`. |
| `http://` returning **403** instead of redirecting | The redirect has not reached that edge yet |
| The old page, or the XML error, after you fixed it | That edge has not picked up the change |

**Wait for the deploy to finish before deciding anything is broken.** Changing
settings again mid-deploy restarts the wait.

---

## If you ended up with two distributions

The wizard can create a **staging** distribution alongside yours, bound to it by a
**continuous deployment policy**. It shows in the list with a type like
*Standard (Staging)* and no alternate domain names.

It is worth removing. If that policy were ever enabled, it would send a share of
your real visitors to the staging copy.

In this order:

1. **Remove the policy.** Open your **primary** distribution (the one with
   `ophosp.com`) → find its **Continuous deployment** section → delete or detach the
   policy. The policy lives on the primary, not the staging one.
2. **Disable** the staging distribution. **Wait** until it finishes deploying.
3. **Delete** it.

Double-check the ID before disabling — the two IDs can differ by a single
character, and disabling the primary takes the site down.

| Error | Meaning |
|---|---|
| *"The distribution you are trying to delete has not been disabled."* | Disable it and **wait** for that to finish deploying |
| *"The specified staging distribution is currently used by a continuous deployment policy."* | Remove the policy from the **primary** distribution first |

---

## Shipping a new build

Four steps. The third is the easy one to forget.

1. Build and package the zip.
2. **S3** → `download` → upload it named exactly **`Open-Hospitality-Windows.zip`**.
   It replaces the old one, so every link ever shared keeps working.
3. **Update the checksum on the page.** `index.html` prints the zip's SHA-256 so a
   cautious owner can verify a file Windows is already warning them about. A stale
   one is worse than none — it accuses a good file of having been tampered with.

   ```powershell
   (Get-FileHash "Open-Hospitality-Windows.zip" -Algorithm SHA256).Hash.ToLower()
   ```

   Paste it into `index.html`, upload `index.html` again.
4. **Invalidate** so CloudFront stops serving the old copies: distribution →
   **Invalidations** → **Create invalidation** →

   ```
   /index.html
   /download/Open-Hospitality-Windows.zip
   ```

   The first 1,000 paths a month are free.

To confirm the live download matches the page:

```bash
curl -sS -o live.zip https://ophosp.com/download/Open-Hospitality-Windows.zip
sha256sum live.zip
curl -sS https://ophosp.com/ | grep -o '[0-9a-f]\{64\}' | head -1
```

The two hashes must be identical.

---

## What it costs

A couple of dollars a month at this size. Route 53 hosted zone: **$0.50/month**.
S3: a few cents. CloudFront: largely inside the free tier, with the 115 MB
download being most of the traffic.

**The things that can actually cost money are all opt-in:** AWS WAF (Part 5, step 3),
*Legacy clients support* at $600/month (Part 6), and a download that goes viral.
Keep the budget alert.

## When something goes wrong

| What you see | Usually |
|---|---|
| Anything odd **right after a change** | A deploy still in progress. [Wait first.](#waiting-for-a-deploy) |
| **403 AccessDenied** (XML) at `https://ophosp.com/`, but `/index.html` works | **Default root object** not set (Part 6) |
| **403 AccessDenied** everywhere, including `/index.html` | The bucket policy from Part 5, step 2 is missing |
| Certificate list **empty** | Certificate not in **N. Virginia**, or not yet *Issued* |
| Certificate stuck **Pending validation** | Nameserver change at your registrar not live yet |
| `ophosp.com` has **no address** (`nslookup` shows a name, no IPs) | The A alias record (Part 7) is missing |
| `www` gives a **certificate warning** | `www.ophosp.com` is not an alternate domain name on the distribution |
| `www` **does not resolve** | The `www` A alias record is missing |
| Red banner on the **Route 53 Dashboard** | Harmless — use **Hosted zones** instead |
| Updated the page, still see the old one | Invalidate it; hard-refresh with Ctrl+Shift+R |

---

## Appendix — the command line, for later

Once it exists, a release is three commands. Needs the AWS CLI and `aws configure`.

```bash
aws s3 sync site/ s3://ophosp-site/ --exclude "DEPLOY.md" \
  --cache-control "public, max-age=300"

aws s3 cp Open-Hospitality-Windows.zip \
  s3://ophosp-site/download/Open-Hospitality-Windows.zip \
  --content-type application/zip --cache-control "public, max-age=86400"

aws cloudfront create-invalidation --distribution-id <DISTRIBUTION_ID> \
  --paths "/index.html" "/download/Open-Hospitality-Windows.zip"
```

`<DISTRIBUTION_ID>` is the ID column in CloudFront's distribution list.

## Two notes about the page

- **It makes no third-party requests** — no web fonts, analytics or tag manager. A
  page whose main claim is that your figures never leave your computer should not
  load a tracker to say so. Add analytics and that claim needs rewording.
- **When the app is signed**, delete the "Windows will warn you" box. Leaving it
  up after it stops being true teaches people to skim the page's warnings.

# Putting ophosp.com on AWS — start to finish

*Written for someone who has not done this before. Everything is done by
clicking in the AWS console; there is a command-line version at the end for
later. Set aside about an hour, most of it waiting.*

You will end up with:

```
ophosp.com ──► Route 53 (DNS) ──► CloudFront (HTTPS + CDN) ──► S3 (the files)
```

Three services, and you only ever touch S3 again after this.

---

## Before you start

You need:

- your AWS account, signed in
- the domain `ophosp.com`, registered at GoDaddy/Namecheap/whoever — you will
  change one setting there, near the end
- the folder `site/` from this repository (`index.html`, `favicon.svg`)
- the build: `dist/Open Hospitality 2026-09-12.zip`

**Do this first if you have not:** search for **Billing** in the console →
**Budgets** → create a zero-spend or $5 budget with an email alert. This whole
setup costs a couple of dollars a month, but a budget means a mistake cannot
quietly become a bill.

### One thing to know about regions

The AWS console has a **region selector in the top-right** (it will say
something like *N. Virginia* or *Ohio*). Most of this does not care which region
you are in — **except the certificate, which must be requested in N. Virginia
(us-east-1)**. CloudFront accepts certificates from that region and no other.
This is the single most common thing to get wrong, and the error it produces
later ("no certificates available") does not explain itself.

---

## Part 1 — Make the bucket that holds the files

1. In the console search bar, type **S3**, open it.
2. **Create bucket**.
3. **Bucket name:** `ophosp-site`.
   Bucket names are global across all of AWS, so if it is taken, add something —
   `ophosp-site-2026`. Write down whatever you choose; you need it twice more.
4. **Region:** pick the one nearest you. It does not matter much — CloudFront
   caches worldwide regardless.
5. Leave **Block all public access ticked**. This looks wrong and is not. The
   bucket stays private and CloudFront is given its own key to the door, which
   means nobody can bypass the CDN and hammer your bucket directly.
6. Leave everything else as it is. **Create bucket**.

> **Checkpoint:** you can see `ophosp-site` in your bucket list.

## Part 2 — Put the files in it

1. Click into the bucket → **Upload** → **Add files**.
2. Add `site/index.html` and `site/favicon.svg`. **Upload**.
3. Back in the bucket, **Create folder** → name it `download` → **Create**.
4. Open the `download` folder → **Upload** → **Add files** → choose
   `dist/Open Hospitality 2026-09-12.zip`.
5. **Before you press Upload**, rename it so the link never changes between
   releases. The easiest way: rename the file on your computer first, to

   ```
   Open-Hospitality-Windows.zip
   ```

   No spaces — spaces in a URL become `%20` and make an ugly link. The page
   already points at `/download/Open-Hospitality-Windows.zip`.
6. **Upload.** It is 115 MB, so give it a minute.

> **Checkpoint:** the bucket contains `index.html`, `favicon.svg`, and
> `download/Open-Hospitality-Windows.zip`. Clicking any of them and trying the
> object URL gives **Access Denied** — correct. They are private until
> CloudFront is in front of them.

## Part 3 — Get the HTTPS certificate

**Switch the region to N. Virginia (us-east-1) first.** Top-right selector.
Check it. This is the step people redo.

1. Search for **Certificate Manager**, open it.
2. **Request** → **Request a public certificate** → **Next**.
3. **Fully qualified domain name:** `ophosp.com`
4. **Add another name to this certificate:** `www.ophosp.com`
5. **Validation method: DNS validation** (the recommended one).
6. **Request.**

It now says **Pending validation**. It stays that way until Part 5, when the
DNS exists. Leave it; come back to it.

> **Checkpoint:** a certificate for `ophosp.com` exists, status *Pending
> validation*, and the region says N. Virginia.

## Part 4 — Set up DNS in Route 53

Your domain is registered elsewhere. You are **not moving the registration** —
only telling the world that AWS answers DNS questions about it. That is what
lets `ophosp.com` itself (not just `www.`) point at CloudFront, which most
registrars cannot do.

1. Search for **Route 53** → **Hosted zones** → **Create hosted zone**.
2. **Domain name:** `ophosp.com`. **Type:** Public hosted zone. **Create.**
3. You now see records, including one of type **NS** with four values like:

   ```
   ns-123.awsdns-45.com.
   ns-678.awsdns-90.net.
   ns-1234.awsdns-56.org.
   ns-789.awsdns-12.co.uk.
   ```

   **Copy all four.**
4. **Now go to your registrar** (GoDaddy, Namecheap, wherever you bought it).
   Find the domain, then a setting called **Nameservers** — usually under
   "DNS", "Manage DNS" or "Domain settings". Choose **Custom nameservers** and
   paste the four AWS ones, replacing what is there.
   Most registrars want them without the trailing dot.
5. Save.

This takes anywhere from a few minutes to a day to take effect, though an hour
is typical. Nothing else is blocked by it — carry on.

Now finish the certificate:

6. Back in **Certificate Manager** (N. Virginia), open the pending certificate.
7. There is a button: **Create records in Route 53**. Click it, confirm.
   It writes the validation records for you.
8. Wait. The status becomes **Issued** — a few minutes once DNS has propagated.

> **Checkpoint:** the certificate says **Issued**. If it is still pending after
> an hour or two, the nameserver change at your registrar has probably not
> taken effect yet.

## Part 5 — Create the CloudFront distribution

This is what serves the site over HTTPS and puts it on a CDN.

1. Search for **CloudFront** → **Create distribution**.
2. **Origin domain:** click the box and pick your `ophosp-site` bucket from the
   list. Pick the bucket itself, not a website endpoint.
3. **Origin access:** choose **Origin access control settings (recommended)**.
   - Click **Create new OAC** → accept the defaults → **Create**.
   - A yellow banner appears saying the bucket policy must be updated. There is
     a **Copy policy** button. **Copy it now** — you will paste it in Part 6.
4. **Viewer protocol policy:** **Redirect HTTP to HTTPS**.
5. **Alternate domain names (CNAME):** add two — `ophosp.com` and
   `www.ophosp.com`.
6. **Custom SSL certificate:** pick the certificate you just had issued.
   *If the list is empty, the certificate is not in N. Virginia, or is not yet
   Issued.*
7. **Default root object:** type `index.html`.
   Without it, visiting `https://ophosp.com/` returns an XML error instead of
   your page.
8. **Create distribution.**

It now says **Deploying** for 5–15 minutes. That is normal.

> **Checkpoint:** the distribution has a domain name like
> `d1234abcd.cloudfront.net`. Note it down.

## Part 6 — Let CloudFront into the bucket

Remember that policy you copied.

1. **S3** → your bucket → **Permissions** tab.
2. **Bucket policy** → **Edit** → paste the policy → **Save changes**.

If you lost it: CloudFront → your distribution → **Origins** → select the
origin → **Edit** → the copy button is there again.

> **Checkpoint:** once the distribution finishes deploying, open
> `https://d1234abcd.cloudfront.net` in a browser. **You should see the page.**
> If you see Access Denied, the bucket policy did not save.

## Part 7 — Point the domain at it

1. **Route 53** → **Hosted zones** → `ophosp.com` → **Create record**.
2. **Record name:** leave it **empty** (that means the domain itself).
3. **Record type:** **A**.
4. Turn **Alias** **on**.
5. **Route traffic to:** *Alias to CloudFront distribution* → pick yours.
6. **Create records.**
7. Do it again for `www`: same, but **Record name:** `www`.

An **Alias A record** is an AWS-specific trick. A normal CNAME cannot sit on a
bare domain, which is exactly why the DNS had to move to Route 53.

> **Checkpoint:** after a few minutes, `https://ophosp.com` shows the page with
> a padlock, and so does `https://www.ophosp.com`.

## Part 8 — Check it properly

- Visit `https://ophosp.com` — page loads, padlock present.
- Click **Download for Windows** — a 115 MB zip starts downloading.
- Visit `http://ophosp.com` (no s) — it should redirect to `https`.
- Open it on your phone — the layout should stack to one column.

---

## Shipping a new build later

Four steps. The third is the one that is easy to forget.

1. Build and zip as before.
2. **S3** → bucket → `download` → **Upload** the new zip, named exactly
   `Open-Hospitality-Windows.zip`. It replaces the old one, so every link
   anybody has ever shared keeps working.
3. **Update the checksum on the page.** `index.html` prints the download's
   SHA-256 so a cautious owner can verify a file Windows is already warning them
   about. A stale checksum is worse than none — it accuses a good file of having
   been tampered with. Get the new one with:

   ```powershell
   (Get-FileHash "dist\Open Hospitality 2026-09-12.zip" -Algorithm SHA256).Hash.ToLower()
   ```

   Paste it into `index.html`, then upload `index.html` again.
4. **Tell CloudFront to forget the old copies.** CloudFront → your distribution
   → **Invalidations** → **Create invalidation** → enter:

   ```
   /index.html
   /download/Open-Hospitality-Windows.zip
   ```

   Without this, people keep getting the old page and the old download for up to
   a day. The first 1,000 invalidation paths each month are free.

---

## What this costs

Pennies to a couple of dollars a month at this size, and the download dominates
it — 115 MB per install. The Route 53 hosted zone is **$0.50/month** flat. S3
storage for a 115 MB file is a few cents. CloudFront has a generous free tier.

The thing that could actually cost money is the download going viral. If that
would worry you, set the budget alert mentioned at the top.

## When something goes wrong

| What you see | What it usually is |
|---|---|
| **Access Denied** at the CloudFront URL | The bucket policy from Part 6 was not pasted or not saved |
| An **XML error** at `https://ophosp.com/` | **Default root object** is not set to `index.html` (Part 5, step 7) |
| The certificate list is **empty** in CloudFront | The certificate is not in **N. Virginia (us-east-1)**, or is not yet *Issued* |
| Certificate stuck on **Pending validation** | The nameserver change at your registrar has not taken effect yet — give it longer |
| Domain does not resolve at all | Same thing. Check at [dnschecker.org](https://dnschecker.org) that the NS records show the AWS nameservers |
| You updated the page and still see the old one | Invalidate it (see above), and hard-refresh with Ctrl+Shift+R |
| **"Your connection is not private"** | The alternate domain names in Part 5 step 5 do not match what you typed in the browser |

---

## Appendix — the same thing from the command line

Once you have done it once, updates are two commands. Requires the AWS CLI and
`aws configure` with an access key.

```bash
# the page: short cache, so a change is visible within the hour
aws s3 sync site/ s3://ophosp-site/ --exclude "DEPLOY.md" \
  --cache-control "public, max-age=300"

# the build: stable name, long cache, correct type
aws s3 cp "dist/Open Hospitality 2026-09-12.zip" \
  s3://ophosp-site/download/Open-Hospitality-Windows.zip \
  --content-type application/zip \
  --cache-control "public, max-age=86400"

# and tell the CDN to forget the old copies
aws cloudfront create-invalidation --distribution-id <YOUR_ID> \
  --paths "/index.html" "/download/Open-Hospitality-Windows.zip"
```

## Two notes about the page itself

- **It makes no third-party requests.** No web fonts, no analytics, no tag
  manager. That is deliberate: a page whose main claim is that your figures
  never leave your computer should not load a tracker to say so. If you add
  analytics later, that claim needs rewording.
- **When the app is signed**, delete the "Windows will warn you" box from
  `index.html`. Leaving it up after it stops being true teaches people to skim
  past the page's warnings.

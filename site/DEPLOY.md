# Putting ophosp.com on AWS

One page, one download, no server to run. S3 holds the files, CloudFront serves
them over HTTPS, Route 53 points the domain at CloudFront.

Everything below is once-only except [Shipping a new build](#shipping-a-new-build),
which you will do every release.

---

## What you are building

```
ophosp.com ──► Route 53 ──► CloudFront ──► S3 bucket (private)
                              │              ├── index.html
                              │              ├── favicon.svg
                              │              └── download/Open-Hospitality-Windows.zip
                              └── ACM certificate (must be in us-east-1)
```

The bucket stays **private**. CloudFront reaches it through an Origin Access
Control, so nobody can bypass the CDN and hit S3 directly.

## 1. The bucket

```bash
aws s3api create-bucket --bucket ophosp-site --region us-east-1
aws s3api put-public-access-block --bucket ophosp-site \
  --public-access-block-configuration \
  "BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true"
```

*(Outside us-east-1, add `--create-bucket-configuration LocationConstraint=<region>`.)*

## 2. The certificate

It **must** be in `us-east-1` — CloudFront accepts certificates from nowhere else,
whatever region the bucket is in.

```bash
aws acm request-certificate --region us-east-1 \
  --domain-name ophosp.com \
  --subject-alternative-names www.ophosp.com \
  --validation-method DNS
```

Then add the CNAME it asks for to the Route 53 hosted zone. If the zone is
already in this account, the console's "Create records in Route 53" button does
it for you. Validation usually completes in minutes.

## 3. The distribution

Simplest through the console: **CloudFront → Create distribution**.

| Setting | Value |
|---|---|
| Origin | the `ophosp-site` bucket |
| Origin access | **Origin access control**, then "Copy policy" and paste it into the bucket policy |
| Viewer protocol policy | Redirect HTTP to HTTPS |
| Default root object | `index.html` |
| Alternate domain names | `ophosp.com`, `www.ophosp.com` |
| Custom SSL certificate | the ACM certificate from step 2 |
| Price class | whichever suits — the site is one page |

## 4. The DNS

Two **A records, alias targets**, pointing at the distribution — not CNAMEs,
which cannot sit on an apex domain:

- `ophosp.com` → the CloudFront distribution
- `www.ophosp.com` → the CloudFront distribution

## 5. Upload

Run from the repository root. The two `sync` calls differ on purpose: the page
must be re-fetched when it changes, the download need not be.

```bash
# the page: short cache, so a change is visible within the hour
aws s3 sync site/ s3://ophosp-site/ --exclude "DEPLOY.md" \
  --cache-control "public, max-age=300"

# the build: stable name, long cache, correct type
aws s3 cp "dist/Open Hospitality 2026-09-12.zip" \
  s3://ophosp-site/download/Open-Hospitality-Windows.zip \
  --content-type application/zip \
  --cache-control "public, max-age=86400"
```

---

## Shipping a new build

Four steps, and the third is the one that is easy to forget.

1. Build and package:

   ```bash
   uv run --extra desktop --group build python scripts/desktop/build.py
   ```

   then zip `dist/Open Hospitality/` with `docs/desktop/INSTALL.md` inside it as
   `Read me first.md`.

2. Upload it over the same key (`download/Open-Hospitality-Windows.zip`), so
   every link ever shared keeps working.

3. **Update the checksum and the size on the page.** `index.html` prints the
   SHA-256 so a cautious owner can verify a download that Windows is already
   warning them about. A stale checksum is worse than none — it tells them the
   file has been tampered with when it has not.

   ```bash
   # Windows
   (Get-FileHash "dist\Open Hospitality 2026-09-12.zip" -Algorithm SHA256).Hash.ToLower()
   ```

4. Invalidate the page so CloudFront serves it:

   ```bash
   aws cloudfront create-invalidation --distribution-id <ID> \
     --paths "/index.html" "/download/Open-Hospitality-Windows.zip"
   ```

## Notes

- **The page makes no third-party requests.** No fonts, no analytics, no tag
  manager. That is deliberate: a page claiming your figures never leave your
  computer should not load a tracker to say so. Keep it that way.
- **Cost** is pennies a month at this traffic, and the download dominates it —
  115 MB per install. CloudFront's free tier covers a good deal of that.
- **`Mac — coming soon`** is a disabled span, not a link. When there is a Mac
  build, it becomes a second `.btn` beside the Windows one.
- **When the app is signed**, delete the "Windows will warn you" box. Leaving it
  up after it stops being true teaches people to ignore the page.

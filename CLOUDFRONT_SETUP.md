# CloudFront CDN Setup Guide

This guide walks you through creating an AWS CloudFront distribution in front of your
`ikigembe-movies` S3 bucket (`eu-north-1`).

---

## Step 1 — Open the CloudFront Console

1. Sign in to the [AWS Console](https://console.aws.amazon.com)
2. Search for **CloudFront** in the search bar → click it
3. Click **Create distribution**

---

## Step 2 — Configure the Origin (S3 Bucket)

| Field | Value |
|---|---|
| **Origin domain** | `ikigembe-movies.s3.eu-north-1.amazonaws.com` |
| **Origin access** | **Origin access control settings (recommended)** |
| **Create new OAC** | Click → give it any name → Create |

> **Why OAC?** Origin Access Control lets CloudFront access your private S3 bucket
> securely without making the bucket fully public.

After selecting OAC you'll see a banner:
> *"You must update the S3 bucket policy"* — you will do this in Step 4.

---

## Step 3 — Configure Default Cache Behaviour

| Field | Value |
|---|---|
| **Viewer protocol policy** | Redirect HTTP to HTTPS |
| **Allowed HTTP methods** | GET, HEAD |
| **Cache policy** | `CachingOptimized` (AWS managed) |
| **Compress objects automatically** | Yes |

---

## Step 4 — Configure Distribution Settings

| Field | Value |
|---|---|
| **Price class** | Use all edge locations (best for global audience) |
| **Default root object** | *(leave blank)* |

Click **Create distribution**.

> ⏳ CloudFront takes **~5–10 minutes** to deploy globally.

---

## Step 5 — Update the S3 Bucket Policy

After the distribution is created, AWS shows a banner with a ready-made bucket policy.
Copy it, then:

1. Go to **S3** → `ikigembe-movies` → **Permissions** → **Bucket policy**
2. Paste the policy and click **Save changes**

The policy will look like:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "Service": "cloudfront.amazonaws.com"
      },
      "Action": "s3:GetObject",
      "Resource": "arn:aws:s3:::ikigembe-movies/*",
      "Condition": {
        "StringEquals": {
          "AWS:SourceArn": "arn:aws:cloudfront::<YOUR_ACCOUNT_ID>:distribution/<YOUR_DIST_ID>"
        }
      }
    }
  ]
}
```

---

## Step 6 — Get Your CloudFront Domain

1. In the CloudFront console, open your new distribution
2. Copy the **Distribution domain name** — it looks like:
   ```
   d1234abcdef8.cloudfront.net
   ```

---

## Step 7 — Add the Domain to `.env`

Open `.env` and fill in:

```ini
AWS_CLOUDFRONT_DOMAIN = d1234abcdef8.cloudfront.net
```

Also add this to your **Render environment variables** (Dashboard → Ikigembe service → Environment):

| Key | Value |
|---|---|
| `AWS_CLOUDFRONT_DOMAIN` | `d1234abcdef8.cloudfront.net` |

---

## Step 8 — Configure CORS on S3 (if not already done)

Go to **S3** → `ikigembe-movies` → **Permissions** → **Cross-origin resource sharing (CORS)**
and add:

```json
[
  {
    "AllowedHeaders": ["*"],
    "AllowedMethods": ["GET", "HEAD"],
    "AllowedOrigins": ["*"],
    "ExposeHeaders": ["ETag"],
    "MaxAgeSeconds": 3000
  }
]
```

---

## Verification

After restarting your Django server, call any movie endpoint and confirm image/video URLs
start with your CloudFront domain:

```bash
curl https://ikigembe-backend.onrender.com/api/movies/discover/
```

Expected URL shape in the response:
```
"thumbnail_url": "https://d1234abcdef8.cloudfront.net/media/movies/thumbnails/..."
```

---

## How Files Still Get Uploaded

Uploads still go **directly to S3** from your backend (via `boto3` presigned URLs and
`django-storages`). CloudFront only handles **serving/reading** the files. This is the
standard pattern — no changes to your upload logic are needed.

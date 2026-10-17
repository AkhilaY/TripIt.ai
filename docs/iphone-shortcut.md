# Put TripIt in the iPhone share sheet

iPhones only let App Store apps add themselves to the share sheet. A free **Shortcut** does the same job: it sends the reel link to your TripIt server in the background, so you never leave TikTok or Instagram.

The TripIt web app shows these steps under **Settings**, with your server address and API key ready to copy.

You need:
- your server address, e.g. `https://tripit-yourname.fly.dev`
- your `APP_API_KEY`

## Option A: save in the background (recommended)

1. Open the **Shortcuts** app and tap **+** to create a shortcut. Tap the name at the top and call it **TripIt**.
2. Tap the **ⓘ** button at the bottom (on iOS 17 and later, tap the name at the top, then **Details**). Turn on **Show in Share Sheet** and tap **Done**.
3. The first block now reads **Receive _Any_ input from Share Sheet**. Tap **Any**, choose **Clear**, then select only **URLs** and **Text**. (TikTok shares a link; some apps share text with the link inside.)
4. Tap **Add Action**, search for **Get Contents of URL** and add it.
5. Replace the URL in that action with `https://<your-server>/v1/jobs`.
6. Tap the **›** arrow on the action to show its options:
   - **Method:** `POST`
   - **Headers:** tap **Add new header**. Key `X-API-Key`, value your API key.
   - **Request Body:** `JSON`. Tap **Add new field → Text**, name it `url`, and for the value tap **Select Variable** and pick **Shortcut Input**.
7. Optional: add **Show Notification** after it with the text `Saved to TripIt. Finding places…`.
8. Tap **Done**.

### Use it

- **TikTok:** tap **Share**, scroll the bottom row to **More (•••)**, then **TripIt**.
- **Instagram:** tap the **paper plane**, then **Share to…** (or **More**), then **TripIt**.
- The first time, iOS may ask whether TripIt can send data to your server. Tap **Always Allow**.
- To keep TripIt near the front of the share sheet, scroll the app row to the end, tap **Edit Actions**, and add TripIt to **Favorites**.

Open the TripIt web app 30–60 seconds later. The places are in a trip for that city, and the **Imports** tab shows progress.

## Option B: open TripIt each time (simplest)

This variant needs no API key in the Shortcut, because the web app already has it. The trade-off is that it switches to TripIt every time.

1. Create a shortcut named **TripIt** with **Show in Share Sheet** on, receiving **URLs** and **Text** (steps 1–3 above).
2. Add the action **URL** with `https://<your-server>/share?url=` and then insert the **Shortcut Input** variable right after `url=`.
3. Add **Open URLs**.

Sharing a reel now opens TripIt in Safari, which saves the link and shows its progress. Safari keeps its own sign-in, separate from the Home Screen app, so enter your API key once in Safari too.

## Troubleshooting

| What you see | Fix |
|---|---|
| Notification says saved, but nothing shows in Imports | Check the header name is exactly `X-API-Key` and the URL ends in `/v1/jobs`. |
| Import fails with "Couldn't download this reel" | The reel is private, or it's from Instagram and the server needs cookies (see the README). |
| TripIt isn't in the share sheet | In the shortcut's details, check **Show in Share Sheet** is on and the input types include **URLs**. |
| "Invalid API key" in Imports or the web app | The key in the Shortcut or the web app doesn't match `APP_API_KEY` on the server. |

import express from "express";
import cors from "cors";
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";

import {
  generateRegistrationOptions,
  verifyRegistrationResponse,
  generateAuthenticationOptions,
  verifyAuthenticationResponse
} from "@simplewebauthn/server";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const app = express();
const PORT = process.env.PORT || 3000;


/* =========================================================
   EASY BROWSER SETTINGS
   ========================================================= */

const RP_NAME = "Easy Browser";

/*
  Your GitHub Pages domain.
*/
const RP_ID = "varunkoneri.github.io";

/*
  Your actual GitHub Pages origin.
*/
const ORIGIN = "https://varunkoneri.github.io";


/* =========================================================
   MIDDLEWARE
   ========================================================= */

app.use(express.json());

app.use(
  cors({
    origin: ORIGIN,
    methods: ["GET", "POST"],
    credentials: false
  })
);


/* =========================================================
   SIMPLE FILE DATABASE
   ========================================================= */

const DATA_FILE =
  path.join(__dirname, "users.json");


function loadUsers() {

  if (!fs.existsSync(DATA_FILE)) {
    return {};
  }

  try {
    return JSON.parse(
      fs.readFileSync(DATA_FILE, "utf8")
    );
  } catch {
    return {};
  }
}


function saveUsers(users) {

  fs.writeFileSync(
    DATA_FILE,
    JSON.stringify(users, null, 2)
  );
}


const users = loadUsers();


/*
  Temporary challenges.

  In a larger production app these should be stored
  in a proper database/session store.
*/

const registrationChallenges = {};
const authenticationChallenges = {};


/* =========================================================
   HOME / HEALTH CHECK
   ========================================================= */

app.get("/", (req, res) => {

  res.json({
    name: "Easy Browser WebAuthn Server",
    status: "online"
  });

});


app.get("/health", (req, res) => {

  res.json({
    ok: true
  });

});


/* =========================================================
   REGISTER - GET OPTIONS
   ========================================================= */

app.post(
  "/register/options",
  async (req, res) => {

    try {

      const username =
        String(req.body.username || "")
          .trim()
          .toLowerCase();


      if (!username) {

        return res.status(400).json({
          error: "Username is required"
        });

      }


      /*
        Create user if they don't exist.
      */

      if (!users[username]) {

        const userId =
          crypto.randomUUID();

        users[username] = {

          username,

          userId,

          passkeys: []

        };

        saveUsers(users);

      }


      const user =
        users[username];


      /*
        Don't allow duplicate registration
        of the same credentials.
      */

      const options =
        await generateRegistrationOptions({

          rpName: RP_NAME,

          rpID: RP_ID,

          userName: username,

          userID:
            new TextEncoder().encode(
              user.userId
            ),

          attestationType: "none",

          excludeCredentials:
            user.passkeys.map(
              passkey => ({
                id: passkey.id,
                transports:
                  passkey.transports
              })
            ),

          authenticatorSelection: {

            residentKey: "required",

            userVerification: "required",

            authenticatorAttachment:
              "platform"

          },

          supportedAlgorithmIDs: [
            -7,
            -257
          ]

        });


      /*
        Save challenge.
      */

      registrationChallenges[username] =
        options.challenge;


      res.json(options);

    } catch (error) {

      console.error(error);

      res.status(500).json({
        error: error.message
      });

    }

  }
);


/* =========================================================
   REGISTER - VERIFY
   ========================================================= */

app.post(
  "/register/verify",
  async (req, res) => {

    try {

      const username =
        String(req.body.username || "")
          .trim()
          .toLowerCase();


      const response =
        req.body.response;


      if (!username || !response) {

        return res.status(400).json({
          error: "Invalid registration data"
        });

      }


      const user =
        users[username];


      if (!user) {

        return res.status(404).json({
          error: "User not found"
        });

      }


      const expectedChallenge =
        registrationChallenges[username];


      if (!expectedChallenge) {

        return res.status(400).json({
          error: "Registration challenge expired"
        });

      }


      const verification =
        await verifyRegistrationResponse({

          response,

          expectedChallenge,

          expectedOrigin: ORIGIN,

          expectedRPID: RP_ID,

          requireUserVerification: true

        });


      if (!verification.verified) {

        return res.status(400).json({
          verified: false,
          error: "Face ID/passkey verification failed"
        });

      }


      const registrationInfo =
        verification.registrationInfo;


      const credential =
        registrationInfo.credential;


      /*
        Save the public credential.

        The private key never comes to this server.
      */

      user.passkeys.push({

        id: credential.id,

        publicKey:
          Buffer.from(
            credential.publicKey
          ).toString("base64"),

        counter:
          credential.counter,

        transports:
          credential.transports || [],

        deviceType:
          registrationInfo.credentialDeviceType,

        backedUp:
          registrationInfo.credentialBackedUp

      });


      saveUsers(users);


      delete registrationChallenges[username];


      res.json({

        verified: true,

        message:
          "Easy Browser passkey registered successfully"

      });

    } catch (error) {

      console.error(error);

      res.status(400).json({

        verified: false,

        error: error.message

      });

    }

  }
);


/* =========================================================
   LOGIN - GET OPTIONS
   ========================================================= */

app.post(
  "/login/options",
  async (req, res) => {

    try {

      const username =
        String(req.body.username || "")
          .trim()
          .toLowerCase();


      if (!username) {

        return res.status(400).json({
          error: "Username is required"
        });

      }


      const user =
        users[username];


      if (!user) {

        return res.status(404).json({
          error:
            "No Easy Browser passkey found for this username"
        });

      }


      if (!user.passkeys.length) {

        return res.status(404).json({
          error:
            "No passkey registered"
        });

      }


      const options =
        await generateAuthenticationOptions({

          rpID: RP_ID,

          allowCredentials:
            user.passkeys.map(
              passkey => ({

                id: passkey.id,

                transports:
                  passkey.transports

              })
            ),

          userVerification: "required"

        });


      authenticationChallenges[username] =
        options.challenge;


      res.json(options);

    } catch (error) {

      console.error(error);

      res.status(500).json({
        error: error.message
      });

    }

  }
);


/* =========================================================
   LOGIN - VERIFY
   ========================================================= */

app.post(
  "/login/verify",
  async (req, res) => {

    try {

      const username =
        String(req.body.username || "")
          .trim()
          .toLowerCase();


      const response =
        req.body.response;


      if (!username || !response) {

        return res.status(400).json({
          error: "Invalid login data"
        });

      }


      const user =
        users[username];


      if (!user) {

        return res.status(404).json({
          error: "User not found"
        });

      }


      const expectedChallenge =
        authenticationChallenges[username];


      if (!expectedChallenge) {

        return res.status(400).json({
          error: "Login challenge expired"
        });

      }


      /*
        Find the passkey used by the device.
      */

      const passkey =
        user.passkeys.find(
          item =>
            item.id === response.id
        );


      if (!passkey) {

        return res.status(404).json({
          error: "Passkey not found"
        });

      }


      const verification =
        await verifyAuthenticationResponse({

          response,

          expectedChallenge,

          expectedOrigin: ORIGIN,

          expectedRPID: RP_ID,

          requireUserVerification: true,

          credential: {

            id:
              passkey.id,

            publicKey:
              new Uint8Array(
                Buffer.from(
                  passkey.publicKey,
                  "base64"
                )
              ),

            counter:
              passkey.counter,

            transports:
              passkey.transports

          }

        });


      if (!verification.verified) {

        return res.status(401).json({

          verified: false,

          error:
            "Face ID verification failed"

        });

      }


      /*
        Update authenticator counter.
      */

      passkey.counter =
        verification.authenticationInfo
          .newCounter;


      saveUsers(users);


      delete authenticationChallenges[username];


      res.json({

        verified: true,

        username,

        message:
          "Easy Browser login successful"

      });

    } catch (error) {

      console.error(error);

      res.status(401).json({

        verified: false,

        error: error.message

      });

    }

  }
);


/* =========================================================
   START SERVER
   ========================================================= */

app.listen(PORT, () => {

  console.log(
    `Easy Browser authentication server running on port ${PORT}`
  );

});

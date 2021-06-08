# Localization
If you want to translate the Integration to your own language, the only thing you have to do is:
1. Fork this project
2. Go to the directory [`custom_components/google_home/translations`](/custom_components/google_home/translations)
3. Create a new `.json` file with the name of your desired language in the [BCP47](https://www.rfc-editor.org/info/bcp47) format.
4. Fill the file with translations from the `en.json` model, or the following template:
   ```json
   {
     "config": {
       "step": {
         "user": {
           "title": "Google Home authentication",
           "description": "If you need help with the configuration have a look here: https://github.com/leikoilja/ha-google-home. Use your google account username and app password. It's safer/easier to generate an app password and use it instead of the actual password. It still has the same access as the regular password, but still better than using the real password while scripting. (https://myaccount.google.com/apppasswords). If not, regular google account password should work.",
           "data": {
             "username": "Google account username",
             "password": "Google account app password"
           }
         }
       },
       "error": {
         "auth": "Username/Password is incorrect. If your google account has 2FA enabled please generate app password (https://myaccount.google.com/apppasswords). If authentication still fails refer to https://github.com/leikoilja/ha-google-home#troubleshooting"
       },
       "abort": {
         "single_instance_allowed": "Only a single instance is allowed."
       }
     },
     "options": {
       "step": {
         "init": {
           "data": {
             "data_collection": "Allow anonymous diagnostic data collection (See https://github.com/leikoilja/ha-google-home#diagnostic-data-collection). Restart required."
           }
         }
       }
     }
   }
   ```
 5. Commit your modifications.
 6. Open a PR.
 7. Enjoy.

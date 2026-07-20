# bgremove.py
A plugin for GIMP (GNU Image Manipulation Program).
## Example
![images/huskys.webp](images/huskys.webp)

## How it works

1. The plugin saves the current layer to disk,
2. runs `backgroundremover` command-line tool,
3. and loads the changed image as a new layer.

**Make it your own.** Easily adapt it to run any command. We use `backgroundremover` but you can alternatively use `rembg` or some other tool. This template can turn *any* command-line tool into a GIMP plugin. Merely edit `bgremove.py` with any text editor, search for the command string, and modify it to your liking. Make it run a batch of commands if you want. The sky's the limit!

	```python
    command = [
        "backgroundremover",
        "-i", str(input_path),
        "-o", str(output_path),
        # Optional parameters can be added here, e.g., --model u2net
    ]
	```

## Dependencies

1. **Before installing**, make sure you have Gimp version 3 or above. That should ensure you have the necessary Python environment and any required libraries. 
2. **Install `backgroundremover`** and its dependencies. On Python 3.14+, the `numba` dev build may be incompatible with newer `numpy` versions. Install compatible versions:
	```shell
	pip install --upgrade pip
	pip install "numpy<2.5" "numba>=0.66.0"
	pip install backgroundremover
	```
3. **Find `backgroundremover`** and install it somewhere in your path. We linked it to `~/.local/bin/`.
    ```shell
    ln -s `which backgroundremover` ~/.local/bin/
    ```
## Plugin setup

Updated plugin is available from https://github.com/themanyone/bgremove

    ```shell
    cd ~/.config/GIMP/3.0/plug-ins/
    git clone https://github.com/themanyone/bgremove.git
    ```

**Restart GIMP:** The "Background Remove" plugin should now appear in your GIMP <Image>/Filters/AI/ menu. The AI is not the fastest. It might take 30 seconds to work the first time. You may change what menu to place it on by modifying this line near the bottom of bgremove.py

    ```python
        # Add to the Layer/Transparency menu
        procedure.add_menu_path ("<Image>/Filters/AI")
    ```

## Thanks for trying out gimp-plugins!

* GitHub https://github.com/themanyone
* YouTube https://www.youtube.com/themanyone
* Mastodon https://mastodon.social/@themanyone
* Linkedin https://www.linkedin.com/in/henry-kroll-iii-93860426/
* Buy me a coffee https://buymeacoffee.com/isreality
* TheNerdShow.com https://thenerdshow.com

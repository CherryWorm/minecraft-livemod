package gm.updater;

import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;
import java.security.GeneralSecurityException;
import java.security.KeyFactory;
import java.security.MessageDigest;
import java.security.PublicKey;
import java.security.Signature;
import java.security.spec.X509EncodedKeySpec;
import java.time.Duration;
import java.util.ArrayList;
import java.util.Base64;
import java.util.HexFormat;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Properties;
import java.util.Set;
import java.util.regex.Pattern;
import java.util.stream.Stream;

/**
 * Brings the game's mods up to date before it starts, so nobody has to download the pack again. Prism runs this as the instance's
 * pre-launch command, and the game starts once this exits.
 *
 * <p>This runs with all the power of any program on a friend's PC, so it only installs what's listed in a manifest signed with a key
 * that never goes near the server, and the manifest can't be older than one it's already taken. A compromised server can only make it
 * do nothing. Anything going wrong leaves the mods as they were and the game starting anyway, because Prism won't start it if this fails.
 *
 * <p>It can't update itself, so changing it means everyone downloads the pack once more. Keep it small. broker/client_release.py writes
 * the manifest.
 */
public final class Updater {
	private static final String SETTINGS = "livingmod-updater.properties";
	private static final String STATE = "livingmod-updater.state";
	private static final String WORKING_FOLDER = "livingmod-updater-download";
	private static final String KEY_RESOURCE = "/client_release.pub";
	private static final String HEADER = "livingmod-update 1";
	// The start of how Java wants an Ed25519 public key, with only the raw key left to add.
	private static final String ED25519_PREFIX = "302a300506032b6570032100";
	private static final Pattern PATH = Pattern.compile("(mods|config|resourcepacks)/[A-Za-z0-9+_-][A-Za-z0-9+._-]*");
	private static final Pattern HASH = Pattern.compile("[0-9a-f]{64}");
	private static final int MOST_MANIFEST_BYTES = 256 * 1024;
	private static final long MOST_FILE_BYTES = 256L * 1024 * 1024;
	private static final Duration CONNECT_TIME = Duration.ofSeconds(5);
	private static final Duration FILE_TIME = Duration.ofMinutes(2);
	private static final Duration ALL_TIME = Duration.ofMinutes(5);

	private final Path root;
	private final HttpClient http = HttpClient.newBuilder().connectTimeout(CONNECT_TIME).followRedirects(HttpClient.Redirect.NEVER).build();
	private final long deadline = System.nanoTime() + ALL_TIME.toNanos();

	private Updater(Path root) {
		this.root = root;
	}

	public static void main(String[] args) {
		try {
			new Updater(Path.of("").toAbsolutePath()).run();
		} catch (Throwable problem) {
			log("Starting the game without updating: " + problem);
		}
		System.exit(0);
	}

	private static void log(String line) {
		System.out.println("[Living Mod updater] " + line);
	}

	private record Listed(String path, String hash, long size) {}

	private record Manifest(long generation, List<Listed> files) {}

	private void run() throws IOException, GeneralSecurityException, InterruptedException {
		Path settingsFile = this.root.resolve(SETTINGS);
		if (!Files.exists(settingsFile)) {
			log("Nothing says where updates come from.");
			return;
		}
		Properties settings = new Properties();
		try (InputStream input = Files.newInputStream(settingsFile)) {
			settings.load(input);
		}
		String base = settings.getProperty("url", "").replaceAll("/+$", "");

		byte[] body = fetch(base + "/manifest", MOST_MANIFEST_BYTES);
		byte[] signature = Base64.getDecoder().decode(new String(fetch(base + "/manifest.sig", 1024), StandardCharsets.US_ASCII).trim());
		Signature verifier = Signature.getInstance("Ed25519");
		verifier.initVerify(pinnedKey());
		verifier.update(body);
		if (!verifier.verify(signature)) {
			log("The update isn't signed by the key this was made with, so it's being ignored.");
			return;
		}
		Manifest manifest = parse(new String(body, StandardCharsets.UTF_8));

		long lastGeneration = 0;
		Set<String> managed = new LinkedHashSet<>();
		Path stateFile = this.root.resolve(STATE);
		if (Files.exists(stateFile)) {
			for (String line : Files.readAllLines(stateFile, StandardCharsets.UTF_8)) {
				String[] parts = line.split(" ", 2);
				if (parts.length == 2 && parts[0].equals("generation")) {
					lastGeneration = Long.parseLong(parts[1]);
				} else if (parts.length == 2 && parts[0].equals("managed") && PATH.matcher(parts[1]).matches()) {
					managed.add(parts[1]);
				}
			}
		}
		if (manifest.generation() < lastGeneration) {
			log("This update is older than one already taken, so it's being ignored.");
			return;
		}

		Path working = this.root.resolve(WORKING_FOLDER);
		removeFolder(working);
		Files.createDirectories(working);
		try {
			// Everything's fetched and checked before anything changes, so a failure halfway leaves a working set of mods.
			List<Listed> changed = new ArrayList<>();
			for (Listed file : manifest.files()) {
				Path target = this.root.resolve(file.path());
				if (!Files.exists(target) || !hashOf(target).equals(file.hash())) {
					download(base, file, working.resolve(file.hash()));
					changed.add(file);
				}
			}
			for (Listed file : changed) {
				Path target = this.root.resolve(file.path());
				Files.createDirectories(target.getParent());
				Files.move(working.resolve(file.hash()), target, StandardCopyOption.REPLACE_EXISTING);
				log("Updated " + file.path());
			}
			Set<String> listed = new LinkedHashSet<>();
			manifest.files().forEach(file -> listed.add(file.path()));
			for (String old : managed) {
				// Only what this put there. A mod someone added for themselves is theirs.
				if (!listed.contains(old) && Files.deleteIfExists(this.root.resolve(old))) {
					log("Removed " + old);
				}
			}
			StringBuilder state = new StringBuilder("generation " + manifest.generation() + "\n");
			listed.forEach(path -> state.append("managed ").append(path).append('\n'));
			Path temporary = this.root.resolve(STATE + ".tmp");
			Files.writeString(temporary, state.toString(), StandardCharsets.UTF_8);
			Files.move(temporary, stateFile, StandardCopyOption.REPLACE_EXISTING);
			log(changed.isEmpty() ? "Everything's up to date." : "Updated " + changed.size() + " files.");
		} finally {
			removeFolder(working);
		}
	}

	private static Manifest parse(String text) throws IOException {
		String[] lines = text.split("\n");
		if (lines.length < 2 || !lines[0].equals(HEADER) || !lines[1].startsWith("generation ")) {
			throw new IOException("a manifest this can't read");
		}
		long generation = Long.parseLong(lines[1].substring("generation ".length()));
		List<Listed> files = new ArrayList<>();
		for (int index = 2; index < lines.length; index++) {
			String[] parts = lines[index].split(" ");
			if (parts.length != 4 || !parts[0].equals("file") || !PATH.matcher(parts[1]).matches() || !HASH.matcher(parts[2]).matches()) {
				throw new IOException("a manifest line this can't read: " + lines[index]);
			}
			long size = Long.parseLong(parts[3]);
			if (size < 0 || size > MOST_FILE_BYTES) {
				throw new IOException("a file too big to fetch: " + parts[1]);
			}
			files.add(new Listed(parts[1], parts[2], size));
		}
		return new Manifest(generation, files);
	}

	private PublicKey pinnedKey() throws IOException, GeneralSecurityException {
		try (InputStream input = Updater.class.getResourceAsStream(KEY_RESOURCE)) {
			if (input == null) {
				throw new IOException("no pinned key");
			}
			byte[] raw = Base64.getDecoder().decode(new String(input.readAllBytes(), StandardCharsets.US_ASCII).trim());
			byte[] prefix = HexFormat.of().parseHex(ED25519_PREFIX);
			byte[] encoded = new byte[prefix.length + raw.length];
			System.arraycopy(prefix, 0, encoded, 0, prefix.length);
			System.arraycopy(raw, 0, encoded, prefix.length, raw.length);
			return KeyFactory.getInstance("Ed25519").generatePublic(new X509EncodedKeySpec(encoded));
		}
	}

	private InputStream open(String url) throws IOException, InterruptedException {
		if (System.nanoTime() > this.deadline) {
			throw new IOException("taking too long");
		}
		HttpRequest request = HttpRequest.newBuilder(URI.create(url)).timeout(FILE_TIME).GET().build();
		HttpResponse<InputStream> response = this.http.send(request, HttpResponse.BodyHandlers.ofInputStream());
		if (response.statusCode() != 200) {
			response.body().close();
			throw new IOException(response.statusCode() + " from the update server");
		}
		return response.body();
	}

	private byte[] fetch(String url, int most) throws IOException, InterruptedException {
		try (InputStream input = open(url)) {
			byte[] body = input.readNBytes(most + 1);
			if (body.length > most) {
				throw new IOException("too much from " + url);
			}
			return body;
		}
	}

	private void download(String base, Listed file, Path target) throws IOException, InterruptedException, GeneralSecurityException {
		MessageDigest digest = MessageDigest.getInstance("SHA-256");
		long total = 0;
		try (InputStream input = open(base + "/files/" + file.hash()); OutputStream output = Files.newOutputStream(target)) {
			byte[] buffer = new byte[64 * 1024];
			int read;
			while ((read = input.read(buffer)) != -1) {
				total += read;
				if (total > file.size()) {
					throw new IOException(file.path() + " is bigger than it should be");
				}
				digest.update(buffer, 0, read);
				output.write(buffer, 0, read);
			}
		}
		if (total != file.size() || !HexFormat.of().formatHex(digest.digest()).equals(file.hash())) {
			throw new IOException(file.path() + " didn't arrive as signed");
		}
	}

	private static String hashOf(Path path) throws IOException, GeneralSecurityException {
		MessageDigest digest = MessageDigest.getInstance("SHA-256");
		try (InputStream input = Files.newInputStream(path)) {
			byte[] buffer = new byte[64 * 1024];
			int read;
			while ((read = input.read(buffer)) != -1) {
				digest.update(buffer, 0, read);
			}
		}
		return HexFormat.of().formatHex(digest.digest());
	}

	private static void removeFolder(Path folder) throws IOException {
		if (!Files.isDirectory(folder)) {
			return;
		}
		try (Stream<Path> files = Files.list(folder)) {
			for (Path file : files.toList()) {
				Files.deleteIfExists(file);
			}
		}
		Files.deleteIfExists(folder);
	}
}

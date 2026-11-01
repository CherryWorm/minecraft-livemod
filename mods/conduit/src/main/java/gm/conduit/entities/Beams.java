package gm.conduit.entities;

import eu.pb4.polymer.virtualentity.api.ElementHolder;
import eu.pb4.polymer.virtualentity.api.attachment.ManualAttachment;
import eu.pb4.polymer.virtualentity.api.elements.BlockDisplayElement;
import gm.conduit.api.Beam;
import net.minecraft.server.MinecraftServer;
import net.minecraft.server.level.ServerLevel;
import net.minecraft.server.level.ServerPlayer;
import net.minecraft.server.network.ServerGamePacketListenerImpl;
import net.minecraft.util.Brightness;
import net.minecraft.world.level.block.state.BlockState;
import net.minecraft.world.phys.Vec3;
import org.joml.Matrix4f;
import org.joml.Quaternionf;
import org.joml.Vector3f;

import java.util.ArrayList;
import java.util.List;

/**
 * Long straight lines of light, made of stretched block displays. These are cut into pieces, because a client works out fog at a model's
 * corners and blends between them, so one huge piece comes out the colour of the fog. A piece is only sent to players whose client has that
 * chunk, which is how far anyone can see anything: a client won't draw an entity in a chunk it hasn't got, however it's told to.
 */
public final class Beams {
	private static final double PIECE_LENGTH = 16.0;
	private static final int MOST_PIECES = 2048;
	private static final int UPDATE_EVERY_TICKS = 20;
	/** A display's own limit on how far it's drawn, in units of 64 blocks. The chunks a client has are the real limit. */
	private static final float VIEW_RANGE = 16.0F;
	private static final Vector3f UP = new Vector3f(0.0F, 1.0F, 0.0F);
	private static final List<Line> LINES = new ArrayList<>();
	private static int pieces;

	private Beams() {}

	/** Null if there are too many in the world already. */
	public static Beam create(ServerLevel level, Vec3 from, Vec3 to, float thickness, BlockState looks, int seconds) {
		Line line = new Line(level, looks, thickness, seconds > 0 ? level.getServer().getTickCount() + seconds * 20L : Long.MAX_VALUE);
		if (!line.build(from, to)) {
			return null;
		}
		LINES.add(line);
		line.updateWatchers();
		return line;
	}

	static void tick(MinecraftServer server) {
		if (LINES.isEmpty()) {
			return;
		}
		boolean update = server.getTickCount() % UPDATE_EVERY_TICKS == 0;
		for (Line line : List.copyOf(LINES)) {
			if (server.getTickCount() >= line.until) {
				line.remove();
			} else if (update) {
				line.updateWatchers();
			}
		}
	}

	private static final class Line implements Beam {
		private final ServerLevel level;
		private final BlockState looks;
		private final float thickness;
		private final long until;
		private final List<Piece> built = new ArrayList<>();

		Line(ServerLevel level, BlockState looks, float thickness, long until) {
			this.level = level;
			this.looks = looks;
			this.thickness = thickness;
			this.until = until;
		}

		boolean build(Vec3 from, Vec3 to) {
			double length = from.distanceTo(to);
			int count = Math.max(1, (int) Math.ceil(length / PIECE_LENGTH));
			if (pieces + count > MOST_PIECES) {
				return false;
			}
			pieces += count;
			Vec3 step = to.subtract(from).scale(1.0 / count);
			for (int index = 0; index < count; index++) {
				this.built.add(new Piece(this.level, from.add(step.scale(index)), step, this.looks, this.thickness));
			}
			return true;
		}

		@Override
		public void moveTo(Vec3 from, Vec3 to) {
			if (isRemoved()) {
				return;
			}
			clear();
			if (build(from, to)) {
				updateWatchers();
			}
		}

		private void clear() {
			pieces -= this.built.size();
			this.built.forEach(Piece::destroy);
			this.built.clear();
		}

		@Override
		public void remove() {
			clear();
			LINES.remove(this);
		}

		@Override
		public boolean isRemoved() {
			return !LINES.contains(this);
		}

		void updateWatchers() {
			this.built.forEach(Piece::updateWatchers);
		}
	}

	private static final class Piece {
		private final ServerLevel level;
		private final Vec3 position;
		private final ElementHolder holder = new ElementHolder();

		Piece(ServerLevel level, Vec3 position, Vec3 step, BlockState looks, float thickness) {
			this.level = level;
			this.position = position;
			BlockDisplayElement display = new BlockDisplayElement(looks);
			Vector3f along = new Vector3f((float) step.x, (float) step.y, (float) step.z);
			float length = along.length();
			// Stands the unit cube on its middle, then tips and stretches it along the line.
			display.setTransformation(new Matrix4f()
					.rotate(new Quaternionf().rotationTo(UP, along.div(Math.max(length, 1.0E-4F))))
					.scale(thickness, length, thickness)
					.translate(-0.5F, 0.0F, -0.5F));
			display.setBrightness(Brightness.FULL_BRIGHT);
			display.setViewRange(VIEW_RANGE);
			display.setShadowRadius(0.0F);
			this.holder.addElement(display);
			new ManualAttachment(this.holder, level, () -> this.position);
		}

		void updateWatchers() {
			for (ServerPlayer player : this.level.players()) {
				boolean sees = player.getChunkTrackingView().contains((int) Math.floor(this.position.x / 16.0), (int) Math.floor(this.position.z / 16.0));
				if (sees) {
					this.holder.startWatching(player);
				} else {
					this.holder.stopWatching(player);
				}
			}
			for (ServerGamePacketListenerImpl watching : List.copyOf(this.holder.getWatchingPlayers())) {
				if (watching.player.hasDisconnected() || watching.player.level() != this.level) {
					this.holder.stopWatching(watching);
				}
			}
		}

		void destroy() {
			this.holder.destroy();
		}
	}
}

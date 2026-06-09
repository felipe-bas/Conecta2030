/** @file
@copyright
(C) Commsignia Ltd. - All Rights Reserved.
Unauthorised copying of this file, via any medium is strictly prohibited.
Proprietary and confidential.
@date 2021
*/

#include <stddef.h>
#include <stdbool.h>
#include <stdio.h>
#include <unistd.h>
#include <stdlib.h>
#include <string.h>
#include <arpa/inet.h>
#include <netdb.h>
#include <errno.h>
#include <signal.h>
#include <sys/select.h>

#include <asn1/v2x_eu_asn.h>
#include <asn1/v2x_us_asn.h>
#include <asn1/v2x_cn_asn.h>
#include <asn1defs.h>

#include <cms_v2x/api.h>
#include <cms_v2x/wsmp.h>
#include <cms_v2x/fac_types.h>

/** @file
@brief Subscribes to received WSMP with encrypted payload messages.
Decodes UPER to JSON, forwards to connected tablet client(s).
@ingroup ex
*/

#define PORT 8080
#define FILTER_PSID 0x87UL
#define MAX_CLIENTS 10

/* Context type for the notification callback */
typedef struct notif_ctx {
    uint32_t param;
    uint32_t cnt;
} notif_ctx_t;

/* Global state for the tablet TCP connections (multi-client) */
int server_fd = -1;
int client_fds[MAX_CLIENTS];
int num_clients = 0;
int opt = 1;

static void init_clients(void) {
    for (int i = 0; i < MAX_CLIENTS; i++) client_fds[i] = -1;
    num_clients = 0;
}

static int add_client(int fd) {
    for (int i = 0; i < MAX_CLIENTS; i++) {
        if (client_fds[i] < 0) {
            client_fds[i] = fd;
            num_clients++;
            return i;
        }
    }
    return -1; /* Full */
}

static void remove_client(int idx) {
    if (idx >= 0 && idx < MAX_CLIENTS && client_fds[idx] >= 0) {
        close(client_fds[idx]);
        client_fds[idx] = -1;
        num_clients--;
    }
}

static int has_any_client(void) {
    return num_clients > 0;
}

static void broadcast_to_clients(const char *data, size_t len) {
    for (int i = 0; i < MAX_CLIENTS; i++) {
        if (client_fds[i] >= 0) {
            if (send(client_fds[i], data, len, 0) < 0) {
                printf("Client %d send failed, removing.\n", i);
                fflush(stdout);
                remove_client(i);
            }
        }
    }
}

/* Fragment buffers: store formatted JSON payloads until all 3 are ready */
#define FRAG_BUF_SIZE 8192
static char frag_bsm[FRAG_BUF_SIZE];
static char frag_psm[FRAG_BUF_SIZE];
static char frag_tim[FRAG_BUF_SIZE];
static int has_bsm = 0, has_psm = 0, has_tim = 0;

/* Buffer for the last complete unified message (sent to new clients on connect) */
#define LAST_MSG_BUF_SIZE (FRAG_BUF_SIZE * 3 + 64)
static char last_unified_msg[LAST_MSG_BUF_SIZE] = {0};
static size_t last_unified_msg_len = 0;

static void send_unified_if_ready(void) {
    if (!has_bsm || !has_psm || !has_tim) return;

    /* Build unified JSON: {"bsm":<bsm>,"psm":<psm>,"tim":<tim>} */
    size_t total = strlen(frag_bsm) + strlen(frag_psm) + strlen(frag_tim) + 40;
    char *unified = (char *)malloc(total);
    if (!unified) {
        fprintf(stderr, "Malloc failed for unified payload\n");
        return;
    }

    snprintf(unified, total, "{\"bsm\":%s,\"psm\":%s,\"tim\":%s}\n",
             frag_bsm, frag_psm, frag_tim);

    /* Always cache the last complete message for new clients connecting later */
    size_t msg_len = strlen(unified);
    if (msg_len < LAST_MSG_BUF_SIZE) {
        memcpy(last_unified_msg, unified, msg_len + 1);
        last_unified_msg_len = msg_len;
    }

    if (has_any_client()) {
        printf("\n>>> ALL 3 FRAGMENTS READY! Broadcasting to %d client(s) (%zu bytes)...\n",
               num_clients, msg_len);
        fflush(stdout);
        broadcast_to_clients(unified, msg_len);
        printf(">>> UNIFIED MESSAGE BROADCAST COMPLETE!\n");
        fflush(stdout);
    } else {
        printf("\n>>> ALL 3 FRAGMENTS READY! No clients connected - message cached (%zu bytes).\n", msg_len);
        fflush(stdout);
    }

    free(unified);
    has_bsm = has_psm = has_tim = 0;
}

typedef struct {
    const char *key;
    const ASN1CType *asn_type;
} message_mapping_t;

static bool process_uper(const ASN1CType* unused_type, cms_buffer_view_t msg, long long rx_ts, int rssi, int msg_len)
{
    bool error = false;
    void* c_struct = NULL;
    const char *detected_key = NULL;

    printf("[1/5] Processing UPER message (decoding as MessageFrame)...\n");
    fflush(stdout);

    /* Step 1: Decode as US_MessageFrame to get the messageId */
    ASN1Error decode_err = {0};
    int ret = asn1_uper_decode((void**)&c_struct,
                                asn1_type_US_MessageFrame,
                                msg.data, msg.length,
                                &decode_err);

    if (ret < 0 || c_struct == NULL) {
        fprintf(stderr, "Failed to decode UPER as MessageFrame: %s\n",
                decode_err.msg ? decode_err.msg : "unknown error");
        fflush(stderr);
        if (c_struct) asn1_free_value(asn1_type_US_MessageFrame, c_struct);
        return true;
    }

    /* Step 2: Read messageId to identify the message type */
    US_MessageFrame *frame = (US_MessageFrame *)c_struct;
    int msg_id = frame->messageId;

    switch (msg_id) {
        case 20: detected_key = "bsm";     break;
        case 32: detected_key = "psm";     break;
        case 31: detected_key = "tim";     break;
        case 18: detected_key = "mapData"; break;
        case 27: detected_key = "rsa";     break;
        case 19: detected_key = "spat";    break;
        default: detected_key = "unknown"; break;
    }

    printf("Decoded MessageFrame with messageId=%d -> %s\n", msg_id, detected_key);
    fflush(stdout);

    /* Step 3: JER-encode the full MessageFrame to JSON */
    printf("[2/5] UPER Decoded successfully. Encoding to JSON (JER)...\n");
    fflush(stdout);

    uint8_t* jer_ptr = NULL;
    ret = asn1_jer_encode((uint8_t**)&jer_ptr, asn1_type_US_MessageFrame, c_struct);
    if ((ret < 0) || (jer_ptr == NULL)) {
        fprintf(stderr, "JER encoding error for messageId=%d\n", msg_id);
        fflush(stderr);
        error = true;
    }

    if (!error && jer_ptr) {
        /* Sanitize JSON: find start and end braces */
        char *json_start = strchr((char *)jer_ptr, '{');
        char *json_end = strrchr((char *)jer_ptr, '}');
        char *clean_json = NULL;

        if (json_start && json_end && json_end > json_start) {
            size_t json_length = json_end - json_start + 1;
            clean_json = (char *)malloc(json_length + 1);
            if (!clean_json) {
                fprintf(stderr, "Malloc failed for clean_json\n");
                fflush(stderr);
                error = true;
            } else {
                memcpy(clean_json, json_start, json_length);
                clean_json[json_length] = '\0';
                
                // Extract msgCnt for logging
                int msg_cnt = -1;
                char *msg_cnt_str = strstr(clean_json, "\"msgCnt\":");
                if (msg_cnt_str) {
                    msg_cnt_str += strlen("\"msgCnt\":");
                    sscanf(msg_cnt_str, "%d", &msg_cnt);
                }
            }
        } else {
            fprintf(stderr, "Failed to parse clean JSON from jer_ptr\n");
            fflush(stderr);
            error = true;
        }

        if (!error && clean_json) {
            /* -------------------------------------------------------------
               DATA COLLECTION LOGGING
               Extract msgCnt and log (timestamp, type, msgCnt, size, rssi)
               ------------------------------------------------------------- */
            int msg_cnt = -1;
            char *msg_cnt_marker = strstr(clean_json, "\"msgCnt\":");
            if (msg_cnt_marker) {
                sscanf(msg_cnt_marker, "\"msgCnt\":%d", &msg_cnt);
            }

            FILE *fp = fopen("/tmp/log_recepcao.csv", "a");
            if (fp) {
                // Get file size to write header if empty
                fseek(fp, 0, SEEK_END);
                long size = ftell(fp);
                if (size == 0) {
                    fprintf(fp, "rx_timestamp,msg_type,msg_cnt,size_bytes,rssi_dbm\n");
                }
                // Format: rx_timestamp_ms, msg_type, msg_cnt, size_bytes, rssi_dbm
                fprintf(fp, "%lld,%s,%d,%d,%d\n", rx_ts, detected_key, msg_cnt, msg_len, rssi);
                fclose(fp);
            }

            printf("[3/5] Formatting and buffering fragment (type: %s, msgCnt: %d, RSSI: %d)...\n", detected_key, msg_cnt, rssi);
            fflush(stdout);

            if (msg_id == 20) {
                /* BSM: Store the full MessageFrame JSON (app expects { "messageId": 20, "value": {...} }) */
                snprintf(frag_bsm, FRAG_BUF_SIZE, "%s", clean_json);
                has_bsm = 1;
                printf("[4/5] BSM fragment buffered. (has_bsm=%d has_psm=%d has_tim=%d)\n", has_bsm, has_psm, has_tim);
                fflush(stdout);
            } else if (msg_id == 32) {
                /* PSM: Extract the inner "value" object (the raw PSM fields) */
                char *value_marker = strstr(clean_json, "\"value\"");
                char *value_obj_start = value_marker ? strchr(value_marker, '{') : NULL;

                if (value_obj_start) {
                    int depth = 1;
                    char *p = value_obj_start + 1;
                    while (*p && depth > 0) {
                        if (*p == '{') depth++;
                        else if (*p == '}') depth--;
                        p++;
                    }
                    if (depth == 0) {
                        size_t value_len = (p - value_obj_start);
                        if (value_len < FRAG_BUF_SIZE) {
                            memcpy(frag_psm, value_obj_start, value_len);
                            frag_psm[value_len] = '\0';
                            has_psm = 1;
                        }
                    }
                }

                if (!has_psm) {
                    /* Fallback: store full MessageFrame JSON */
                    snprintf(frag_psm, FRAG_BUF_SIZE, "%s", clean_json);
                    has_psm = 1;
                }
                printf("[4/5] PSM fragment buffered. (has_bsm=%d has_psm=%d has_tim=%d)\n", has_bsm, has_psm, has_tim);
                fflush(stdout);
            } else if (msg_id == 31) {
                /* TIM: Extract first dataFrame element from value */
                char *value_marker = strstr(clean_json, "\"value\"");
                char *df_marker = value_marker ? strstr(value_marker, "\"dataFrames\"") : NULL;
                char *df_arr_start = df_marker ? strchr(df_marker, '[') : NULL;
                int tim_stored = 0;

                if (df_arr_start) {
                    char *elem_start = strchr(df_arr_start + 1, '{');
                    if (elem_start) {
                        int depth = 1;
                        char *p = elem_start + 1;
                        while (*p && depth > 0) {
                            if (*p == '{') depth++;
                            else if (*p == '}') depth--;
                            p++;
                        }
                        if (depth == 0) {
                            size_t frame_len = (p - elem_start);
                            if (frame_len < FRAG_BUF_SIZE) {
                                memcpy(frag_tim, elem_start, frame_len);
                                frag_tim[frame_len] = '\0';
                                has_tim = 1;
                                tim_stored = 1;
                                printf("    TIM: Extracted first dataFrame (%zu bytes)\n", frame_len);
                                fflush(stdout);
                            }
                        }
                    }
                }

                if (!tim_stored) {
                    snprintf(frag_tim, FRAG_BUF_SIZE, "%s", clean_json);
                    has_tim = 1;
                    printf("    TIM: dataFrame extraction failed, stored full TIM\n");
                    fflush(stdout);
                }
                printf("[4/5] TIM fragment buffered. (has_bsm=%d has_psm=%d has_tim=%d)\n", has_bsm, has_psm, has_tim);
                fflush(stdout);
            } else {
                /* Other types (MAP, SPAT, RSA): send immediately */
                size_t buffer_size = strlen(clean_json) + strlen(detected_key) + 20;
                char *payload = (char *)malloc(buffer_size);
                if (payload) {
                    snprintf(payload, buffer_size, "{\"%s\":%s}\n", detected_key, clean_json);
                    if (has_any_client()) {
                        broadcast_to_clients(payload, strlen(payload));
                    }
                    free(payload);
                }
                printf("[4/5] Non-alert message (%s) broadcast to %d client(s).\n", detected_key, num_clients);
                fflush(stdout);
            }

            /* Check if all 3 fragments are ready */
            send_unified_if_ready();
        }

        if (clean_json) {
            free(clean_json);
        }
    }

    if (jer_ptr != NULL) {
        asn1_free(jer_ptr);
    }

    if(c_struct != NULL) {
        asn1_free_value(asn1_type_US_MessageFrame, c_struct);
    }

    return error;
}

/* Notification callback to print received message details */
static void wsmp_rx_notif_cb(cms_psid_t psid,
                             const cms_wsmp_rx_notif_data_t* notif,
                             cms_buffer_view_t msg,
                             void* ctx)
{
    if((NULL == notif) || (NULL == msg.data) || (0UL == msg.length) || (NULL == ctx)) {
        fprintf(stderr, "%s NULL argument\n", __func__);
    } else {
        notif_ctx_t* notif_ctx = (notif_ctx_t*)ctx;

        /* Always process UPER so fragment buffers fill up.
         * send_unified_if_ready() will cache the result even with no clients.
         * Clients connecting later will receive the last cached message. */
        if (has_any_client()) {
            printf("\n>>> [RADIO] WSMP Received! Processing... (%d client(s))\n", num_clients);
        } else {
            printf("\n>>> [RADIO] WSMP Received! Processing... (no clients - will cache)\n");
        }
        fflush(stdout);
        
        long long rx_ts = (long long)notif->radio.timestamp;
        int rssi = (int)notif->radio.rssi;
        int msg_len = (int)msg.length;
        
        bool error = process_uper(NULL, msg, rx_ts, rssi, msg_len);
        ++notif_ctx->cnt;
    }
}


int main(int argc, char* argv[])
{
    // Ignore SIGPIPE to prevent the app from crashing if a client disconnects
    signal(SIGPIPE, SIG_IGN);
    
    const char* host = (argc > 1) ? argv[1] : "127.0.0.1";

    // --- CMS V2X Session Setup ---
    cms_session_t session = cms_get_session();
    bool error = cms_api_connect_easy(&session, host);
    if (error) {
        fprintf(stderr, "Failed to connect to V2X Stack API\n");
    }

    /* Create a context for the subscription callback */
    notif_ctx_t filtered_ctx = {
        .param = 1U,
        .cnt = 0U
    };

    // --- TCP Server Setup (IPv6 Dual-Stack) ---
    struct sockaddr_in6 server_addr;
    struct sockaddr_storage client_addr;  // Generic storage for dual-stack
    socklen_t addr_size;

    if ((server_fd = socket(AF_INET6, SOCK_STREAM, 0)) < 0) {
        perror("Socket failed");
        exit(EXIT_FAILURE);
    }

    setsockopt(server_fd, SOL_SOCKET, SO_REUSEADDR, &opt, sizeof(opt));

    // Enable dual-stack: accept both IPv4-mapped and native IPv6 connections
    int v6only = 0;
    setsockopt(server_fd, IPPROTO_IPV6, IPV6_V6ONLY, &v6only, sizeof(v6only));

    memset(&server_addr, 0, sizeof(server_addr));
    server_addr.sin6_family = AF_INET6;
    server_addr.sin6_addr = in6addr_any;
    server_addr.sin6_port = htons(PORT);

    if (bind(server_fd, (struct sockaddr*)&server_addr, sizeof(server_addr)) < 0) {
        perror("Bind failed");
        close(server_fd);
        exit(EXIT_FAILURE);
    }

    if (listen(server_fd, 5) < 0) {
        perror("Listen failed");
        close(server_fd);
        exit(EXIT_FAILURE);
    }

    printf("Server listening on [::]:% d (IPv6 dual-stack, max %d clients)...\n", PORT, MAX_CLIENTS);
    init_clients();

    /* Subscribe to a specific PSID */
    cms_subs_id_t filtered_subs_id = CMS_SUBS_ID_INVALID;
    error = error || cms_wsmp_rx_subscribe(&session,
                                           FILTER_PSID,
                                           &wsmp_rx_notif_cb,
                                           &filtered_ctx,
                                           &filtered_subs_id);
    if(error) {
        printf("Unable to subscribe to WSMP Rx for PSID 0x%llx\n", (unsigned long long)FILTER_PSID);
        fflush(stdout);
    } else {
        // --- Main Loop: Accept clients + monitor disconnections using select() ---
        while (1) {
            fd_set read_fds;
            FD_ZERO(&read_fds);
            FD_SET(server_fd, &read_fds);
            int max_fd = server_fd;

            /* Add all connected clients to the read set */
            for (int i = 0; i < MAX_CLIENTS; i++) {
                if (client_fds[i] >= 0) {
                    FD_SET(client_fds[i], &read_fds);
                    if (client_fds[i] > max_fd) max_fd = client_fds[i];
                }
            }

            /* select() with 1-second timeout */
            struct timeval tv = { .tv_sec = 1, .tv_usec = 0 };
            int ready = select(max_fd + 1, &read_fds, NULL, NULL, &tv);
            if (ready < 0) {
                if (errno == EINTR) continue;
                perror("select failed");
                sleep(1);
                continue;
            }

            /* Check for new incoming connections */
            if (ready > 0 && FD_ISSET(server_fd, &read_fds)) {
                addr_size = sizeof(client_addr);
                int new_fd = accept(server_fd, (struct sockaddr*)&client_addr, &addr_size);
                if (new_fd >= 0) {
                    int idx = add_client(new_fd);
                    if (idx >= 0) {
                        // Protocol-independent address display
                        char addr_str[INET6_ADDRSTRLEN];
                        uint16_t cli_port;
                        if (client_addr.ss_family == AF_INET6) {
                            struct sockaddr_in6 *s6 = (struct sockaddr_in6 *)&client_addr;
                            inet_ntop(AF_INET6, &s6->sin6_addr, addr_str, sizeof(addr_str));
                            cli_port = ntohs(s6->sin6_port);
                        } else {
                            struct sockaddr_in *s4 = (struct sockaddr_in *)&client_addr;
                            inet_ntop(AF_INET, &s4->sin_addr, addr_str, sizeof(addr_str));
                            cli_port = ntohs(s4->sin_port);
                        }
                        printf("Client [%d] connected: %s:%d (total: %d)\n",
                            idx, addr_str, cli_port, num_clients);
                        fflush(stdout);

                        /* Send the last cached unified message immediately so the
                         * client gets data right away without waiting for the next broadcast */
                        if (last_unified_msg_len > 0) {
                            printf("  -> Sending cached last message (%zu bytes) to new client [%d]\n",
                                   last_unified_msg_len, idx);
                            fflush(stdout);
                            if (send(new_fd, last_unified_msg, last_unified_msg_len, 0) < 0) {
                                printf("  -> Failed to send cached message: %s\n", strerror(errno));
                            }
                        }
                    } else {
                        printf("Max clients reached, rejecting connection.\n");
                        fflush(stdout);
                        close(new_fd);
                    }
                }
            }

            /* Check each connected client for disconnection */
            if (ready > 0) {
                for (int i = 0; i < MAX_CLIENTS; i++) {
                    if (client_fds[i] >= 0 && FD_ISSET(client_fds[i], &read_fds)) {
                        char dump_buf[256];
                        ssize_t bytes_read = recv(client_fds[i], dump_buf, sizeof(dump_buf), 0);
                        if (bytes_read <= 0) {
                            printf("Client [%d] disconnected. (total: %d)\n", i, num_clients - 1);
                            fflush(stdout);
                            remove_client(i);
                        }
                    }
                }
            }
        }
    }

    /* Unsubscribe */
    error = error || cms_wsmp_rx_unsubscribe(&session, filtered_subs_id);

    /* Close connection and cleanup */
    cms_api_disconnect(&session);
    cms_api_clean();
    
    for (int i = 0; i < MAX_CLIENTS; i++) {
        if (client_fds[i] >= 0) close(client_fds[i]);
    }
    close(server_fd);

    return (int)error;
}

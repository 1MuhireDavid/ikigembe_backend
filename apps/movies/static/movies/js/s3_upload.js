document.addEventListener('DOMContentLoaded', function () {
    const widgets = document.querySelectorAll('.s3-direct-upload-widget');

    widgets.forEach(widget => {
        const fileInput = widget.querySelector('input[type="file"]');
        const hiddenInput = widget.querySelector('input[type="hidden"]');
        const progressBar = widget.querySelector('.progress-bar');
        const progressText = widget.querySelector('.progress-text');
        const statusIcon = widget.querySelector('.status-icon');
        const previewArea = widget.querySelector('.preview-area');

        // Get limits (no max size limit effective for multipart, but we keep safety)
        const maxSize = parseInt(widget.getAttribute('data-max-size')) || (10 * 1024 * 1024 * 1024); // 10GB default

        // Find the form and submit button
        const form = widget.closest('form');
        const submitBtns = form ? form.querySelectorAll('input[type="submit"], button[type="submit"]') : [];

        function setUploading(isUploading) {
            submitBtns.forEach(btn => {
                btn.disabled = isUploading;
                btn.style.opacity = isUploading ? '0.5' : '1';
                btn.value = isUploading ? 'Uploading...' : 'Save';
            });

            if (isUploading) {
                window.onbeforeunload = () => "Upload in progress. Are you sure you want to leave?";
            } else {
                window.onbeforeunload = null;
            }
        }

        async function uploadFileCheck(file) {
            // 0. Check File Size
            if (file.size > maxSize) {
                alert(`File is too large! Maximum size is ${Math.round(maxSize / 1024 / 1024 / 1024)}GB.`);
                fileInput.value = ''; // Clear selection
                return false;
            }
            return true;
        }

        function getCookie(name) {
            let cookieValue = null;
            if (document.cookie && document.cookie !== '') {
                const cookies = document.cookie.split(';');
                for (let i = 0; i < cookies.length; i++) {
                    const cookie = cookies[i].trim();
                    if (cookie.substring(0, name.length + 1) === (name + '=')) {
                        cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
                        break;
                    }
                }
            }
            return cookieValue;
        }

        fileInput.addEventListener('change', async function (e) {
            const file = e.target.files[0];
            if (!file) return;

            if (!await uploadFileCheck(file)) return;

            // Chunk configuration
            const CHUNK_SIZE = 10 * 1024 * 1024; // 10MB chunks
            const TOTAL_CHUNKS = Math.ceil(file.size / CHUNK_SIZE);
            let uploadId = null;
            let fileKey = null;
            const parts = [];

            try {
                setUploading(true);
                const csrftoken = getCookie('csrftoken');

                statusIcon.textContent = '⏳';
                progressText.textContent = 'Initiating upload...';

                const fieldName = widget.getAttribute('data-field-name');

                // 1. Initiate Multipart Upload
                const initResponse = await fetch('/api/movies/upload/initiate/', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-CSRFToken': csrftoken
                    },
                    body: JSON.stringify({
                        file_name: file.name,
                        file_type: file.type,
                        field_name: fieldName
                    })
                });

                if (!initResponse.ok) {
                    throw new Error(`Failed to initiate upload: ${await initResponse.text()}`);
                }

                const initData = await initResponse.json();
                uploadId = initData.upload_id;
                fileKey = initData.file_key;

                // 2. Upload Parts
                for (let partNumber = 1; partNumber <= TOTAL_CHUNKS; partNumber++) {
                    const start = (partNumber - 1) * CHUNK_SIZE;
                    const end = Math.min(start + CHUNK_SIZE, file.size);
                    const chunk = file.slice(start, end);

                    progressText.textContent = `Uploading part ${partNumber} of ${TOTAL_CHUNKS}...`;

                    // Get presigned URL for this part
                    const signResponse = await fetch('/api/movies/upload/sign-part/', {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json',
                            'X-CSRFToken': csrftoken
                        },
                        body: JSON.stringify({
                            upload_id: uploadId,
                            file_key: fileKey,
                            part_number: partNumber
                        })
                    });

                    if (!signResponse.ok) {
                        throw new Error(`Failed to sign part ${partNumber}: ${await signResponse.text()}`);
                    }

                    const signData = await signResponse.json();
                    const presignedUrl = signData.url;

                    // Upload the chunk to S3
                    // Note: No headers here as presigned URL handles it, but check your CORs!
                    // S3 returns ETag in header
                    const uploadResponse = await fetch(presignedUrl, {
                        method: 'PUT',
                        body: chunk
                    });

                    if (!uploadResponse.ok) {
                        throw new Error(`Failed to upload part ${partNumber}: ${uploadResponse.status} ${uploadResponse.statusText}`);
                    }

                    const eTag = uploadResponse.headers.get('ETag').replace(/"/g, ''); // Remove quotes
                    parts.push({
                        PartNumber: partNumber,
                        ETag: eTag
                    });

                    // Update Progress
                    const percentComplete = (partNumber / TOTAL_CHUNKS) * 100;
                    progressBar.style.width = percentComplete + '%';
                    progressText.textContent = `Uploaded: ${Math.round(percentComplete)}%`;
                }

                // 3. Complete Multipart Upload
                progressText.textContent = 'Finalizing upload...';

                const completeResponse = await fetch('/api/movies/upload/complete/', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-CSRFToken': csrftoken
                    },
                    body: JSON.stringify({
                        upload_id: uploadId,
                        file_key: fileKey,
                        parts: parts
                    })
                });

                if (!completeResponse.ok) {
                    throw new Error(`Failed to complete upload: ${await completeResponse.text()}`);
                }

                // Success
                setUploading(false);
                statusIcon.textContent = '✅';
                progressText.textContent = 'Upload Complete!';
                hiddenInput.value = fileKey;

                // Preview
                if (file.type.startsWith('image/')) {
                    // We need a way to get the public URL. Assuming standard S3 structure for now.
                    // The view logic determines structure, let's just use a placeholder or try to construct it if we knew the domain.
                    // For now, simple text is safer as we don't return the full public URL in complete (we could change that).
                    previewArea.innerHTML = `Image uploaded.`;
                } else if (file.type.startsWith('video/')) {
                    previewArea.innerHTML = `Video uploaded. Ready to save.`;
                }


            } catch (error) {
                console.error(error);
                setUploading(false);
                statusIcon.textContent = '❌';
                progressText.textContent = 'Error: ' + error.message;
                progressBar.style.backgroundColor = 'red';

                // Attempt Abort
                if (uploadId && fileKey) {
                    console.log('Aborting upload...');
                    try {
                        await fetch('/api/movies/upload/abort/', {
                            method: 'POST',
                            headers: {
                                'Content-Type': 'application/json',
                                'X-CSRFToken': getCookie('csrftoken')
                            },
                            body: JSON.stringify({
                                upload_id: uploadId,
                                file_key: fileKey
                            })
                        });
                    } catch (abortError) {
                        console.error('Failed to abort upload:', abortError);
                    }
                }
            }
        });
    });
});
